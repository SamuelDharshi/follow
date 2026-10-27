"""Hyperliquid BTC perp book via the public l2Book WebSocket.

Each l2Book message is a full snapshot of the top 20 levels per side, so there is no incremental state to
break. Two subscriptions run on one connection: the default one ($1 price steps, ~2 bps of depth) gives the
touch and slippage for small sizes; nSigFigs=4 ($10 buckets, 20 buckets ~ 24 bps) gives depth for wider
bands. A band is only reported when the feed reaches across it (ladder_metrics bid_floor/ask_ceiling);
otherwise the value is None. Bucketed levels are rounded toward the spread by the venue (bids down, asks up),
so bucketed depth is a slight lower bound.
"""
import asyncio
import json
import logging

import websockets

from . import config, db
from .ladder import ladder_metrics
from .supervisor import Resync, beat, supervise

log = logging.getLogger("hyperliquid")
VENUE = "hyperliquid"
FINE, COARSE = "fine", "coarse"


def _levels(side):
    return [(float(x["px"]), float(x["sz"])) for x in side]


def merge(fine, coarse):
    """Metrics from the fine book, with bands/sizes it cannot reach filled from the coarse book."""
    fb, fa = fine
    m = ladder_metrics(fb, fa, bid_floor=fb[-1][0] if fb else None, ask_ceiling=fa[-1][0] if fa else None)
    if not m["two_sided"] or not coarse or not coarse[0] or not coarse[1]:
        return m
    cb, ca = coarse
    mc = ladder_metrics(cb, ca, bid_floor=cb[-1][0], ask_ceiling=ca[-1][0])
    if not mc["two_sided"]:
        return m
    mid = m["mid"]
    # depth must be measured around the fine mid; rebuild band sums from the coarse ladder with that mid
    for n in (5, 10, 25):
        lo, hi = mid * (1 - n / 1e4), mid * (1 + n / 1e4)
        if m.get(f"bid_d{n}") is None and cb[-1][0] <= lo:
            m[f"bid_d{n}"] = sum(p * s for p, s in cb if p >= lo)
        if m.get(f"ask_d{n}") is None and ca[-1][0] >= hi:
            m[f"ask_d{n}"] = sum(p * s for p, s in ca if p <= hi)
    from .ladder import walk
    for x in (10_000, 50_000, 100_000):
        k = f"{x // 1000}k"
        if m.get(f"buy_s{k}") is None and (f := walk(ca, x)) is not None:
            m[f"buy_s{k}"] = (f - mid) / mid * 1e4
        if m.get(f"sell_s{k}") is None and (f := walk(cb, x)) is not None:
            m[f"sell_s{k}"] = (mid - f) / mid * 1e4
    return m


async def run_session(con, state: dict) -> None:
    async with websockets.connect(config.HYPERLIQUID_WS, max_size=2**22, ping_interval=20) as ws:
        subs = [{"type": "l2Book", "coin": "BTC"}, {"type": "l2Book", "coin": "BTC", "nSigFigs": 4}]
        for s in subs:
            await ws.send(json.dumps({"method": "subscribe", "subscription": s}))
        latest = {"fine": None, "coarse": None, "time": None}

        async def sampler():
            # sample the most recent state on a fixed clock, independent of message arrival
            while True:
                await asyncio.sleep(config.SAMPLE_SECONDS)
                if latest["fine"] and latest["coarse"]:
                    ts = db.now_ms()
                    db.insert_sample(con, VENUE, ts, latest["time"], None, merge(latest["fine"], latest["coarse"]))
                    state["last_ts"] = ts
                    beat(con, VENUE)
                    con.commit()

        task = asyncio.create_task(sampler())
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m.get("channel") != "l2Book":
                    continue
                d = m["data"]
                lv = d["levels"]
                book = (_levels(lv[0]), _levels(lv[1]))
                # the coarse (nSigFigs=4) feed has every price on a $10 step; the fine feed almost surely does not
                sample = [p for p, _ in book[0][:8] + book[1][:8]]
                is_coarse = bool(sample) and all(p % 10 == 0 for p in sample)
                latest["coarse" if is_coarse else "fine"] = book
                latest["time"] = d["time"]
                if not state["healthy"] and latest["fine"] and latest["coarse"]:
                    state["healthy"] = True
                    db.close_gaps(con, db.now_ms(), VENUE)
                    con.commit()
                    log.info("synced")
            raise Resync("websocket closed")
        finally:
            task.cancel()


async def run_forever(con) -> None:
    await supervise(con, VENUE, lambda state: run_session(con, state))
