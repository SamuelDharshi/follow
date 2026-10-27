"""Reconnect loop shared by every venue: exponential backoff, gap markers, restart-gap detection."""
import asyncio
import logging

from . import db

log = logging.getLogger("supervisor")


class Resync(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def heartbeat_key(venue: str) -> str:
    return f"heartbeat:{venue}"


def beat(con, venue: str, seq=None) -> None:
    db.set_meta(con, heartbeat_key(venue), db.now_ms())
    if seq is not None:
        db.set_meta(con, f"last_sequence:{venue}", seq)


async def supervise(con, venue: str, run_session) -> None:
    """run_session(state) must set state['healthy']=True once synced and call db.close_gaps for the venue."""
    state: dict = {"venue": venue}
    hb = db.get_meta(con, heartbeat_key(venue)) or (db.get_meta(con, "heartbeat") if venue == "strike" else None)
    if hb:  # the time between the last heartbeat and now was not recorded
        db.open_gap(con, int(hb), "recorder_restart", None, None, venue)
        con.commit()
        log.warning("[%s] previous run ended at %s, gap opened", venue, hb)
    backoff = 1.0
    while True:
        state["healthy"] = False
        try:
            await run_session(state)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            reason = e.reason if isinstance(e, Resync) else f"error: {e!r}"
            log.warning("[%s] session ended: %s", venue, reason)
            if con.execute("SELECT COUNT(*) FROM gaps WHERE end_ms IS NULL AND venue=?", (venue,)).fetchone()[0] == 0:
                db.open_gap(con, state.get("last_ts") or db.now_ms(), reason, state.get("last_seq"),
                            state.get("session"), venue)
                con.commit()
        backoff = 1.0 if state.get("healthy") else min(backoff * 2, 30.0)
        await asyncio.sleep(backoff)
