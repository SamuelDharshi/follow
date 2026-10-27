"""Strike L3 recorder: WebSocket + REST snapshot sync, gap detection, automatic re-snapshot.

Follows https://docs.strikefinance.org/api/l3.md: subscribe and buffer, fetch snapshot, drop updates
through snapshot.last_sequence, apply last_sequence+1 onward. A sequence gap, a `clear` action, a book
inconsistency or a disconnect writes a gap marker and rebuilds from a fresh snapshot.
Every event is stored raw; the local book is also sampled every SAMPLE_SECONDS into book_samples.
"""
import asyncio
import json
import logging
import time

import httpx
import websockets

from . import config, db
from .book import BookError, L3Book
from .ladder import ladder_metrics
from .supervisor import Resync, beat, supervise

log = logging.getLogger("strike_l3")
VENUE = "strike"


async def fetch_snapshot(client: httpx.AsyncClient) -> tuple[dict, int]:
    r = await client.get(f"{config.STRIKE_REST}/v2/l3/snapshot", params={"symbol": config.SYMBOL})
    recv = db.now_ms()
    r.raise_for_status()
    snap = r.json()
    if snap.get("type") != "l3_snapshot":
        raise Resync(f"unexpected snapshot payload: {str(snap)[:200]}")
    return snap, recv


async def _reader(ws, queue: asyncio.Queue):
    try:
        async for raw in ws:
            await queue.put((db.now_ms(), raw))
        await queue.put((db.now_ms(), Resync("websocket closed")))
    except Exception as e:  # noqa: BLE001 - any transport failure means resync
        await queue.put((db.now_ms(), Resync(f"disconnect: {e!r}")))


def check_sequence(seq: int, expected: int) -> bool:
    """True if the update should be applied, False if the snapshot already covers it; a gap forces a rebuild."""
    if seq < expected:
        return False
    if seq > expected:
        raise Resync(f"sequence gap: expected {expected}, got {seq}")
    return True


def write_sample(con, book: L3Book, exch_ts):
    bids, asks = book.ladders()
    m = ladder_metrics(bids, asks)  # L3 book is complete: no coverage limits
    now = db.now_ms()
    db.insert_sample(con, VENUE, now, exch_ts, book.sequence, m)
    # latest ladder (aggregated levels) for the incentive designer, which models on the real current book
    db.set_meta(con, "strike_latest_book", json.dumps({"ts": now, "seq": book.sequence, "bids": bids[:400], "asks": asks[:400]}))


async def run_session(con, client: httpx.AsyncClient, state: dict) -> None:
    session = db.next_session(con)
    state["session"] = session
    channel = f"{config.SYMBOL.lower()}@l3"
    async with websockets.connect(f"{config.STRIKE_WS}/ws/l3", compression="deflate", max_size=2**22) as ws:
        await ws.send(json.dumps({"method": "SUBSCRIBE", "params": [channel], "id": 1}))
        queue: asyncio.Queue = asyncio.Queue()
        reader = asyncio.create_task(_reader(ws, queue))
        try:
            snap, recv = await fetch_snapshot(client)
            db.insert_snapshot(con, session, "session_start", snap, recv)
            db.close_gaps(con, snap["timestamp"], VENUE)
            con.commit()
            book = L3Book(snap)
            expected = snap["last_sequence"] + 1
            state["healthy"] = True
            log.info("session %d synced at seq %d (%d bid lvls, %d ask lvls)", session,
                     snap["last_sequence"], len(snap["bids"]), len(snap["asks"]))
            batch: list[dict] = []
            batch_recv = 0
            last_exch = snap["timestamp"]
            last_flush = last_sample = last_cp = time.monotonic()
            last_ev_ts = snap["timestamp"]  # exchange time of the last applied event
            if db.get_meta(con, "quiescent_sampling_since") is None:
                db.set_meta(con, "quiescent_sampling_since", db.now_ms())
            cp_task = None

            def flush():
                nonlocal batch, last_flush
                if batch:
                    db.insert_events(con, session, batch_recv, batch)
                    state["last_ts"] = batch[-1]["timestamp"]
                    batch = []
                state["last_seq"] = expected - 1
                beat(con, VENUE, expected - 1)
                db.set_meta(con, "heartbeat", db.now_ms())  # legacy key
                con.commit()
                last_flush = time.monotonic()

            try:
                while True:
                    try:
                        recv_ts, raw = await asyncio.wait_for(queue.get(), timeout=config.FLUSH_SECONDS)
                    except asyncio.TimeoutError:
                        raw = None
                    if isinstance(raw, Resync):
                        raise raw
                    if raw is not None:
                        msg = json.loads(raw)
                        if "error" in msg:
                            raise Resync(f"server error: {msg['error']}")
                        if msg.get("type") == "l3_update":
                            seq = msg["sequence"]
                            if check_sequence(seq, expected):
                                # sample on Strike's own clock: if this event starts a new burst (>= QUIET_MS after the previous
                                # one) the book is exactly between two refreshes, so sample it BEFORE applying the event
                                if time.monotonic() - last_sample >= config.SAMPLE_SECONDS and msg["timestamp"] - last_ev_ts >= config.QUIET_MS:
                                    last_sample = time.monotonic()
                                    write_sample(con, book, last_ev_ts)
                                last_ev_ts = msg["timestamp"]
                                batch.append(msg)
                                batch_recv = recv_ts
                                expected += 1
                                last_exch = msg["timestamp"]
                                if msg["action"] == "clear":
                                    raise Resync("clear action")
                                try:
                                    book.apply(msg)
                                except BookError as e:
                                    raise Resync(f"book inconsistency: {e}") from e
                    now = time.monotonic()
                    due = now - last_flush
                    if (batch and due >= config.FLUSH_SECONDS) or len(batch) >= 500 or due >= config.HEARTBEAT_SECONDS:
                        flush()
                    # fallback only: never go MAX_SAMPLE_WAIT without a sample (the exact rule above normally fires first)
                    if now - last_sample >= config.MAX_SAMPLE_WAIT:
                        last_sample = now
                        write_sample(con, book, last_exch)
                    if now - last_cp >= config.CHECKPOINT_SECONDS and (cp_task is None or cp_task.done()):
                        last_cp = now
                        cp_task = asyncio.create_task(_checkpoint(con, client, session))
            finally:
                try:
                    flush()
                except Exception:  # noqa: BLE001
                    log.exception("final flush failed")
                if cp_task and not cp_task.done():
                    cp_task.cancel()
        finally:
            reader.cancel()


async def _checkpoint(con, client, session):
    try:
        snap, recv = await fetch_snapshot(client)
        db.insert_snapshot(con, session, "checkpoint", snap, recv)
        con.commit()
        log.info("checkpoint snapshot at seq %d", snap["last_sequence"])
    except Exception:  # noqa: BLE001
        log.exception("checkpoint failed")


async def run_forever(con) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        await supervise(con, VENUE, lambda state: run_session(con, client, state))
