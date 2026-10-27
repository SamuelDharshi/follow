"""Binance BTCUSDT order book (USD-M perpetual by default, spot optional).

Local-book procedure from Binance docs: buffer the diff-depth stream, fetch a 1000-level REST snapshot, drop
events with u < lastUpdateId, the first applied event must satisfy U <= lastUpdateId <= u, and for futures
each following event must have pu == previous u. The REST snapshot only holds 1000 levels per side, so the
price band the book genuinely covers is [lowest snapshot bid, highest snapshot ask]; depth outside it is
reported as unavailable (None), never extrapolated. The session is rebuilt every BINANCE_RESYNC_SECONDS so the
covered band stays centred on the market.
"""
import asyncio
import json
import logging
import time

import httpx
import websockets

from . import config, db
from .ladder import ladder_metrics
from .supervisor import Resync, beat, supervise

log = logging.getLogger("binance")
VENUE = "binance"


MARKETS = {
    "futures": ("wss://fstream.binance.com/ws/btcusdt@depth@100ms", "https://fapi.binance.com/fapi/v1/depth"),
    "spot": ("wss://stream.binance.com:9443/ws/btcusdt@depth@100ms", "https://api.binance.com/api/v3/depth"),
    # Binance's public market-data mirror, reachable where the main domains are blocked
    "spot_mirror": ("wss://data-stream.binance.vision/ws/btcusdt@depth@100ms", "https://data-api.binance.vision/api/v3/depth"),
}


async def pick_market(client: httpx.AsyncClient) -> str:
    """BINANCE_MARKET=auto tries futures, then spot, then the spot mirror; anything else is used as given."""
    if config.BINANCE_MARKET != "auto":
        return config.BINANCE_MARKET
    for m in ("futures", "spot_mirror"):
        try:
            r = await client.get(MARKETS[m][1], params={"symbol": "BTCUSDT", "limit": 5}, timeout=5)
            if r.status_code == 200:
                return m
        except Exception:  # noqa: BLE001
            pass
    raise Resync("no Binance endpoint reachable")


def note_market(con, market: str) -> None:
    """Which instrument fed the dataset is part of the dataset: log every change with its time."""
    import json
    log_ = json.loads(db.get_meta(con, "binance_markets", "[]"))
    if not log_ or log_[-1][1] != market:
        log_.append([db.now_ms(), market])
        db.set_meta(con, "binance_markets", json.dumps(log_))
        con.commit()


def _apply(side: dict, updates):
    for p, q in updates:
        p, q = float(p), float(q)
        if q == 0:
            side.pop(p, None)
        else:
            side[p] = q


async def run_session(con, client: httpx.AsyncClient, state: dict) -> None:
    market = await pick_market(client)
    ws_url, rest_url = MARKETS[market]
    futures = market == "futures"
    async with websockets.connect(ws_url, max_size=2**23) as ws:
        queue: asyncio.Queue = asyncio.Queue()

        async def reader():
            try:
                async for raw in ws:
                    await queue.put(json.loads(raw))
                await queue.put(Resync("websocket closed"))
            except Exception as e:  # noqa: BLE001
                await queue.put(Resync(f"disconnect: {e!r}"))

        task = asyncio.create_task(reader())
        try:
            r = await client.get(rest_url, params={"symbol": "BTCUSDT", "limit": 1000})
            r.raise_for_status()
            snap = r.json()
            last_id = snap["lastUpdateId"]
            bids, asks = {}, {}
            _apply(bids, snap["bids"])
            _apply(asks, snap["asks"])
            bid_floor, ask_ceiling = min(bids), max(asks)
            prev_u = None
            started = False
            t0 = time.monotonic()
            last_sample = 0.0
            exch_ts = None
            while time.monotonic() - t0 < config.BINANCE_RESYNC_SECONDS:
                ev = await asyncio.wait_for(queue.get(), timeout=30)
                if isinstance(ev, Resync):
                    raise ev
                if ev.get("e") != "depthUpdate":
                    continue
                U, u = ev["U"], ev["u"]
                if not started:
                    if u < last_id:
                        continue
                    if U > last_id:
                        raise Resync(f"snapshot too old: U={U} > lastUpdateId={last_id}")
                    started = True
                elif futures and ev["pu"] != prev_u:
                    raise Resync(f"update-id gap: pu={ev['pu']} prev_u={prev_u}")
                elif not futures and U != prev_u + 1:
                    raise Resync(f"update-id gap: U={U} prev_u={prev_u}")
                prev_u = u
                _apply(bids, ev["b"])
                _apply(asks, ev["a"])
                exch_ts = ev.get("T") or ev.get("E")
                if not state["healthy"]:
                    state["healthy"] = True
                    db.close_gaps(con, db.now_ms(), VENUE)
                    con.commit()
                    note_market(con, market)
                    log.info("[%s] synced at update id %d (covered %.1f..%.1f)", market, last_id, bid_floor, ask_ceiling)
                now = time.monotonic()
                if now - last_sample >= config.SAMPLE_SECONDS:
                    last_sample = now
                    bl = sorted(((p, q) for p, q in bids.items() if p >= bid_floor), reverse=True)
                    al = sorted((p, q) for p, q in asks.items() if p <= ask_ceiling)
                    ts = db.now_ms()
                    db.insert_sample(con, VENUE, ts, exch_ts, u, ladder_metrics(bl, al, bid_floor, ask_ceiling))
                    state["last_ts"], state["last_seq"] = ts, u
                    beat(con, VENUE, u)
                    con.commit()
            # scheduled rebuild: not a fault, but the few seconds without samples are recorded as a gap
            raise Resync("scheduled_resync")
        finally:
            task.cancel()


async def run_forever(con) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        await supervise(con, VENUE, lambda state: run_session(con, client, state))
