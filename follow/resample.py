"""Rebuild Strike's historical book_samples from the raw L3 events, sampling only at quiet moments.

Why: Strike refreshes its whole book once a second as one burst of ~190 separately sequenced cancel/open events with no
atomic boundary. Sampling the local book in the middle of a burst sees a half-empty book (about 14% of the old samples).
The raw events are all stored, so the history can be re-derived exactly: replay each session from its start snapshot and
take a sample whenever the stream goes quiet (>= QUIET_MS between consecutive event timestamps).

Run: python -m follow.resample            (rebuilds everything recorded before burst-aware sampling started)
"""
import sys

from . import config, db
from .book import BookError, L3Book
from .ladder import ladder_metrics

QUIET_MS = 50          # events inside one refresh burst are ~1 ms apart; bursts are ~1 s apart
EVERY_MS = 2000        # same cadence as the live sampler


def replay_session(con, session: int, until_ts: int):
    snap_row = con.execute("SELECT body FROM snapshots WHERE session=? AND kind='session_start'", (session,)).fetchone()
    if not snap_row:
        return []
    book = L3Book(db.load_snapshot(snap_row[0]))
    out, next_t, last_ts = [], 0, None
    cur = con.execute(
        "SELECT sequence,action,order_id,taker_order_id,side,price,delta_size,remaining_size,trade_id,ts "
        "FROM l3_events WHERE session=? AND ts<? AND sequence>? ORDER BY sequence", (session, until_ts, book.sequence))
    keys = ("sequence", "action", "order_id", "taker_order_id", "side", "price", "delta_size", "remaining_size", "trade_id", "timestamp")
    for row in cur:
        ev = dict(zip(keys, row))
        if last_ts is not None and ev["timestamp"] - last_ts >= QUIET_MS and last_ts >= next_t:
            bids, asks = book.ladders()
            out.append((last_ts, book.sequence, ladder_metrics(bids, asks)))
            next_t = last_ts + EVERY_MS
        try:
            book.apply(ev)
        except BookError:
            break  # a stored session never has a hole (verified), so this is only a safety stop
        last_ts = ev["timestamp"]
    return out


def main() -> None:
    con = db.connect(config.DB_PATH)
    since = db.get_meta(con, "quiescent_sampling_since")
    until = int(since) if since else db.now_ms()
    sessions = [r[0] for r in con.execute("SELECT DISTINCT session FROM l3_events ORDER BY session")]
    total = 0
    old = con.execute("SELECT COUNT(*) FROM book_samples WHERE venue='strike' AND ts<?", (until,)).fetchone()[0]
    print(f"replaying {len(sessions)} sessions; replacing {old:,} old Strike samples recorded before {until}")
    rebuilt = []
    for s in sessions:
        rows = replay_session(con, s, until)
        rebuilt.extend(rows)
        total += len(rows)
        print(f"  session {s}: {len(rows):,} samples", file=sys.stderr)
    con.execute("DELETE FROM book_samples WHERE venue='strike' AND ts<?", (until,))
    for ts, seq, m in rebuilt:
        db.insert_sample(con, "strike", ts, ts, seq, m)
    db.set_meta(con, "strike_samples_rebuilt_at", db.now_ms())
    con.commit()
    print(f"done: {total:,} burst-aware samples written")


if __name__ == "__main__":
    main()
