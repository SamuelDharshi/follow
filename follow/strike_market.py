"""Strike public market WebSocket (wss://api.strikefinance.org/ws/price): trade tape + bookTicker.

Trades are stored for cross-checking L3 fills (L3 fills carry a numeric trade_id); bookTicker is stored at
most once per second and used to cross-check the best bid/ask of the locally rebuilt L3 book.
"""
import json
import logging
import time

import websockets

from . import config, db
from .supervisor import Resync, beat, supervise

log = logging.getLogger("strike_market")
VENUE = "strike_market"


async def run_session(con, state: dict) -> None:
    async with websockets.connect(f"{config.STRIKE_WS}/ws/price", compression="deflate", max_size=2**22) as ws:
        for i, ch in enumerate(("trade", "bookTicker"), start=1):
            await ws.send(json.dumps({"method": "subscribe", "channel": ch, "symbol": config.SYMBOL, "id": i}))
        db.close_gaps(con, db.now_ms(), VENUE)
        con.commit()
        state["healthy"] = True
        last_tick = 0
        last_commit = time.monotonic()
        async for raw in ws:
            recv = db.now_ms()
            # a frame may hold several JSON messages separated by newlines (not stated in Strike's docs)
            for part in (raw.decode() if isinstance(raw, bytes) else raw).split(chr(10)):
                if not part.strip():
                    continue
                m = json.loads(part)
                if "error" in m and m.get("e") == "error":
                    raise Resync(f"server error: {m['error']}")
                e = m.get("e")
                if e == "trade":
                    con.execute("INSERT OR IGNORE INTO strike_trades VALUES(?,?,?,?,?,?)",
                                (m["t"], m["T"], recv, m["p"], m["q"], 1 if m.get("m") else 0))
                    state["last_ts"] = m["T"]
                elif e == "bookTicker" and m["E"] - last_tick >= 1000:
                    last_tick = m["E"]
                    con.execute("INSERT OR REPLACE INTO strike_ticker VALUES(?,?,?,?,?,?,?)",
                                (m["E"], recv, m.get("u"), float(m["b"]), float(m["B"]), float(m["a"]), float(m["A"])))
                    state["last_ts"] = m["E"]
            if time.monotonic() - last_commit >= 1:
                last_commit = time.monotonic()
                beat(con, VENUE)
                con.commit()
        raise Resync("websocket closed")


async def run_forever(con) -> None:
    await supervise(con, VENUE, lambda state: run_session(con, state))
