"""Build a compact, REAL snapshot of the recorded database so the API can be hosted without the recorder machine.

Keeps every book sample, rollup, gap, fill event, trade and ticker row; drops only the 11M raw cancel/open events (summarised by the
per-minute rollup) and the large snapshot bodies. Nothing is generated or altered. Run: python -m follow.snapshot  -> snapshot/follow-snapshot.db
"""
import json
import os
import sqlite3

from . import config, db

OUT = os.path.join(os.path.dirname(__file__), "..", "snapshot", "follow-snapshot.db")


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    src = db.connect(config.DB_PATH, readonly=True)
    out = sqlite3.connect(OUT)
    out.execute("ATTACH DATABASE ? AS s", (os.path.abspath(config.DB_PATH),))
    out.executescript(db.SCHEMA)
    for t in ("book_samples", "event_minute", "gaps", "strike_trades", "strike_ticker", "alerts"):
        out.execute(f"INSERT INTO main.{t} SELECT * FROM s.{t}")
    out.execute("INSERT INTO main.l3_events SELECT * FROM s.l3_events WHERE action IN ('partial_fill','full_fill')")
    out.execute("INSERT INTO main.meta SELECT * FROM s.meta WHERE key NOT LIKE 'heartbeat%' AND key NOT LIKE 'last_sequence%'")
    n, lo, hi = src.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM l3_events").fetchone()
    last = src.execute("SELECT MAX(ts) FROM book_samples").fetchone()[0]
    db.set_meta(out, "l3_stats", json.dumps({"count": n, "first_ts": lo, "last_ts": hi}))
    db.set_meta(out, "snapshot_as_of", last)
    out.commit()
    out.execute("DETACH DATABASE s")
    out.execute("VACUUM")
    out.close()
    print("snapshot written:", round(os.path.getsize(OUT) / 1e6, 1), "MB; as of", last, "; raw events summarised:", f"{n:,}")


if __name__ == "__main__":
    main()
