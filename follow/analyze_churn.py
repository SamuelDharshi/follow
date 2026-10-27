"""Reproduces the numbers in FEEDBACK.md from the recorded Strike L3 data.

Run: python -m follow.analyze_churn            (uses data/follow.db)
"""
import bisect
import itertools

from . import config, db


def neutral_refreshes(con) -> None:
    """How often does a refresh burst leave the price-level book unchanged? Replays 120k events from a checkpoint."""
    from .book import L3Book

    row = con.execute("SELECT id, session, last_sequence FROM snapshots WHERE kind='checkpoint' ORDER BY id DESC LIMIT 1 OFFSET 2").fetchone()
    if not row:
        return
    sid, session, seq = row
    book = L3Book(db.load_snapshot(con.execute("SELECT body FROM snapshots WHERE id=?", (sid,)).fetchone()[0]))
    keys = ("sequence", "action", "order_id", "taker_order_id", "side", "price", "delta_size", "remaining_size", "trade_id", "timestamp")
    rows = con.execute("SELECT sequence,action,order_id,taker_order_id,side,price,delta_size,remaining_size,trade_id,ts FROM l3_events "
                       "WHERE session=? AND sequence>? ORDER BY sequence LIMIT 120000", (session, seq)).fetchall()
    prev, last_ts, bursts, same, changed = None, None, 0, 0, []
    for r in rows:
        ev = dict(zip(keys, r))
        if last_ts is not None and ev["timestamp"] - last_ts >= 50:  # quiet boundary between bursts
            cur = (dict(book.levels["buy"]), dict(book.levels["sell"]))
            if prev is not None:
                bursts += 1
                if cur == prev:
                    same += 1
                else:
                    changed.append(sum(1 for i in (0, 1) for p in set(cur[i]) | set(prev[i]) if cur[i].get(p) != prev[i].get(p)))
            prev = cur
        book.apply(ev)
        last_ts = ev["timestamp"]
    changed.sort()
    print(f"\n== Are refresh bursts state-neutral? ({len(rows):,} events, {bursts} bursts) ==")
    print(f"  price-level book identical before and after the burst: {same} of {bursts} ({100 * same / max(bursts, 1):.1f}%)")
    if changed:
        print(f"  in the other {len(changed)} bursts the median number of price levels that changed is {changed[len(changed) // 2]} (a burst is ~190 events)")


def main() -> None:
    con = db.connect(config.DB_PATH, readonly=True)
    hi = con.execute("SELECT MAX(ts) FROM l3_events").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM l3_events").fetchone()[0]
    print(f"== Event mix ({total:,} L3 events recorded) ==")
    for action, n in con.execute("SELECT action, COUNT(*) FROM l3_events GROUP BY action ORDER BY 2 DESC"):
        print(f"  {action:<13}{n:>12,}  {100 * n / total:8.4f}%")

    window = 90 * 60 * 1000
    lo = hi - window
    opens = con.execute("SELECT COUNT(*) FROM l3_events WHERE ts>=? AND action='open'", (lo,)).fetchone()[0]
    fills = con.execute("SELECT COUNT(*) FROM l3_events WHERE ts>=? AND action IN ('partial_fill','full_fill')", (lo,)).fetchone()[0]
    print(f"\n== Last 90 minutes ==\n  {opens:,} new orders, {fills} fills -> {opens / max(fills, 1):,.0f} new orders per fill")

    born, life = {}, []
    for oid, act, ts in con.execute(
            "SELECT order_id, action, ts FROM l3_events WHERE ts>=? AND action IN ('open','cancel','full_fill') ORDER BY sequence", (lo,)):
        if act == "open":
            born[oid] = ts
        else:
            t0 = born.pop(oid, None)
            if t0 is not None and act == "cancel":
                life.append(ts - t0)
    life.sort()
    n = len(life)
    pct = lambda p: life[int(n * p)]
    print(f"\n== Resting time of cancelled orders (n={n:,}) ==")
    print(f"  p10 {pct(.1)} ms | p50 {pct(.5)} ms | p90 {pct(.9)} ms | p99 {pct(.99)} ms")
    for t in (500, 1000, 5000):
        print(f"  cancelled within {t:>4} ms: {100 * bisect.bisect_left(life, t) / n:5.1f}%")

    rows = con.execute("SELECT action FROM l3_events WHERE ts BETWEEN ? AND ? ORDER BY sequence", (hi - 600000, hi - 540000)).fetchall()
    runs = [(k, len(list(g))) for k, g in itertools.groupby(r[0] for r in rows)]
    lens = sorted(n for _, n in runs)
    print("\n== Shape of 60 s of the stream (consecutive runs of the same action) ==")
    print(f"  {len(runs)} runs, median run {lens[len(lens) // 2]} events; longest cancel run "
          f"{max(n for k, n in runs if k == 'cancel')}, longest open run {max(n for k, n in runs if k == 'open')}")

    bursts, cur = [], []
    for ts, in con.execute("SELECT ts FROM l3_events WHERE ts BETWEEN ? AND ? ORDER BY sequence", (hi - 600000, hi - 570000)):
        if cur and ts - cur[-1] > 300:
            bursts.append(cur)
            cur = []
        cur.append(ts)
    bursts.append(cur)
    big = [b for b in bursts if len(b) > 20]
    sizes = sorted(len(b) for b in big)
    spans = sorted(b[-1] - b[0] for b in big)
    print(f"\n== Refresh bursts (>20 events, gaps <300 ms) in 30 s ==\n  {len(big)} bursts, median size {sizes[len(sizes) // 2]} events, "
          f"median exchange-time span {spans[len(spans) // 2]} ms")

    d = sorted((r[0] + r[1]) / 2 for r in con.execute(
        "SELECT bid_d10, ask_d10 FROM book_samples WHERE venue='strike' AND two_sided=1 AND bid_d10 IS NOT NULL AND ask_d10 IS NOT NULL AND ts>=?",
        (hi - 24 * 3600 * 1000,)))
    q = lambda p: d[int(len(d) * p)]
    print(f"\n== Depth within 10 bps seen by 2 s samples, last 24 h (n={len(d):,}) ==")
    print(f"  p5 ${q(.05):,.0f} | p50 ${q(.5):,.0f} | p95 ${q(.95):,.0f}  (p95/p5 = {q(.95) / max(q(.05), 1):.0f}x)")
    neutral_refreshes(con)
    since = db.get_meta(con, "quiescent_sampling_since")
    if since:
        s = int(since)
        dq = sorted((r[0] + r[1]) / 2 for r in con.execute(
            "SELECT bid_d10, ask_d10 FROM book_samples WHERE venue='strike' AND two_sided=1 AND bid_d10 IS NOT NULL AND ask_d10 IS NOT NULL AND ts>=?", (s,)))
        if len(dq) > 100:
            print(f"  burst-aware samples only (since quiescent sampling started, n={len(dq):,}): "
                  f"p5 ${dq[int(len(dq) * .05)]:,.0f} | p50 ${dq[len(dq) // 2]:,.0f} | p95 ${dq[int(len(dq) * .95)]:,.0f}")


if __name__ == "__main__":
    main()
