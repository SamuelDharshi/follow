"""Verification on recorded data.

1. Sequence continuity of every session in l3_events.
2. Replay each session's start snapshot + stored events up to every checkpoint snapshot (a fresh REST snapshot
   fetched later) and diff the rebuilt book against it: must match order for order.
3. Cross-check the rebuilt best bid/ask with Strike's separate bookTicker feed.
4. How many L3 fill trade_ids appear on the public trade tape (decides whether M5/M6 may use that tape).

Run: python -m follow.verify
"""
from . import config, db
from .book import BookError, L3Book, snapshot_orders


def replay(con, session: int, start_snap: dict, upto: int, drop_sequence=None) -> L3Book:
    book = L3Book(start_snap)
    rows = con.execute(
        "SELECT sequence,action,order_id,taker_order_id,side,price,delta_size,remaining_size,trade_id,ts "
        "FROM l3_events WHERE session=? AND sequence>? AND sequence<=? ORDER BY sequence",
        (session, start_snap["last_sequence"], upto))
    for r in rows:
        if r[0] == drop_sequence:
            continue
        book.apply(dict(zip(("sequence", "action", "order_id", "taker_order_id", "side", "price", "delta_size",
                             "remaining_size", "trade_id", "timestamp"), r)))
    return book


def diff(book: L3Book, snap: dict) -> int:
    a, b = book.orders_view(), snapshot_orders(snap)
    return len(set(a) ^ set(b)) + sum(1 for k in set(a) & set(b) if a[k] != b[k])


def continuity(con):
    bad = 0
    for (s,) in con.execute("SELECT DISTINCT session FROM l3_events").fetchall():
        n, lo, hi = con.execute("SELECT COUNT(*),MIN(sequence),MAX(sequence) FROM l3_events WHERE session=?", (s,)).fetchone()
        ok = n == hi - lo + 1
        bad += not ok
        print(f"session {s}: {n} events, seq {lo}..{hi} -> {'contiguous' if ok else 'HOLES'}")
    return bad


def checkpoints(con):
    total = mism = 0
    for sid, session, seq in con.execute("SELECT id,session,last_sequence FROM snapshots WHERE kind='checkpoint' ORDER BY id").fetchall():
        start = con.execute("SELECT body FROM snapshots WHERE session=? AND kind='session_start'", (session,)).fetchone()
        if not start:
            continue
        cp = db.load_snapshot(con.execute("SELECT body FROM snapshots WHERE id=?", (sid,)).fetchone()[0])
        try:
            d = diff(replay(con, session, db.load_snapshot(start[0]), seq), cp)
        except BookError as e:
            d = -1
            print("  replay error:", e)
        total += 1
        mism += d != 0
        print(f"checkpoint seq {seq} (session {session}): {'MATCH' if d == 0 else f'MISMATCH ({d})'}")
    return total, mism


def ticker_crosscheck(con):
    """A sample matches when any bookTicker row within +-1.5 s of its exchange time has the same best bid and ask."""
    samples = con.execute("SELECT exch_ts,best_bid,best_ask FROM book_samples WHERE venue='strike' AND two_sided=1 AND exch_ts IS NOT NULL").fetchall()
    if not samples:
        print("ticker cross-check: no samples yet")
        return
    hit = tot = 0
    for ts, bb, ba in samples:
        rows = con.execute("SELECT bid,ask FROM strike_ticker WHERE ts BETWEEN ? AND ?", (ts - 1500, ts + 1500)).fetchall()
        if not rows:
            continue
        tot += 1
        hit += any(abs(bb - b) < 1e-6 and abs(ba - a) < 1e-6 for b, a in rows)
    print(f"ticker cross-check: {hit}/{tot} samples have a matching best bid/ask on bookTicker within 1.5 s")


def trade_ids(con):
    n = con.execute("SELECT COUNT(DISTINCT trade_id) FROM l3_events WHERE trade_id IS NOT NULL").fetchone()[0]
    m = con.execute("SELECT COUNT(DISTINCT e.trade_id) FROM l3_events e JOIN strike_trades t ON t.trade_id=e.trade_id").fetchone()[0]
    print(f"trade ids: {m} of {n} L3 fill trade_ids found on the public trade tape")


async def live_check(seconds: int = 30) -> int:
    """Independent of the recorder: sync a fresh book, run it, then diff it against a brand-new REST snapshot."""
    import asyncio
    import json

    import httpx
    import websockets

    from .strike_l3 import fetch_snapshot
    async with httpx.AsyncClient(timeout=15) as client, websockets.connect(f"{config.STRIKE_WS}/ws/l3", compression="deflate") as ws:
        await ws.send(json.dumps({"method": "SUBSCRIBE", "params": ["btc-usd@l3"], "id": 1}))
        events = []

        async def collect():
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "l3_update":
                    events.append(m)

        task = asyncio.create_task(collect())
        a, _ = await fetch_snapshot(client)
        await asyncio.sleep(seconds)
        b, _ = await fetch_snapshot(client)
        await asyncio.sleep(3)
        task.cancel()
    book = L3Book(a)
    for e in sorted(events, key=lambda e: e["sequence"]):
        if e["sequence"] <= a["last_sequence"]:
            continue
        if e["sequence"] > b["last_sequence"]:
            break
        book.apply(e)
    d = diff(book, b)
    print(f"live check: snapshot seq {a['last_sequence']} + {len(events)} events -> seq {book.sequence} vs REST seq {b['last_sequence']}: "
          f"{'MATCH' if d == 0 and book.sequence == b['last_sequence'] else f'MISMATCH ({d} orders differ)'}")
    return 0 if d == 0 and book.sequence == b["last_sequence"] else 1


def main():
    import sys
    if "--live" in sys.argv:
        import asyncio
        raise SystemExit(asyncio.run(live_check()))
    con = db.connect(config.DB_PATH, readonly=True)
    holes = continuity(con)
    total, mism = checkpoints(con)
    ticker_crosscheck(con)
    trade_ids(con)
    print(f"RESULT: {holes} sessions with holes, {mism}/{total} checkpoint mismatches")
    raise SystemExit(1 if holes or mism else 0)


if __name__ == "__main__":
    main()
