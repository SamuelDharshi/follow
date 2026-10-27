"""Read-side metrics engine: rolls book_samples and l3_events into 1-minute / hourly / daily series.

Windows are fixed buckets of unix time. Each metric row carries its sample count and coverage (samples seen /
samples expected) so gaps show up as low coverage instead of being averaged away.
"""
from . import config

STEPS = {"minute": 60_000, "hour": 3_600_000, "day": 86_400_000}
VENUES = ("strike", "binance", "hyperliquid")
SPREAD_BPS = 5.0


def _avg(col):
    return f"AVG({col})"


def book_series(con, venue: str, step: str, start: int, end: int) -> list[dict]:
    ms = STEPS[step]
    expected = ms / (config.SAMPLE_SECONDS * 1000)
    sql = f"""
    SELECT (ts/{ms})*{ms} AS t, COUNT(*) AS n, SUM(two_sided) AS n2,
      AVG(CASE WHEN two_sided=1 AND spread_bps<={SPREAD_BPS} THEN 1.0 ELSE 0.0 END) AS m1,
      AVG(spread_bps) AS spread_bps,
      AVG(bid_d5), AVG(ask_d5), AVG(bid_d10), AVG(ask_d10), AVG(bid_d25), AVG(ask_d25),
      AVG(buy_s10k), AVG(sell_s10k), AVG(buy_s50k), AVG(sell_s50k), AVG(buy_s100k), AVG(sell_s100k),
      COUNT(buy_s10k), COUNT(sell_s10k), COUNT(buy_s50k), COUNT(sell_s50k), COUNT(buy_s100k), COUNT(sell_s100k),
      AVG(mid)
    FROM book_samples WHERE venue=? AND ts>=? AND ts<? GROUP BY t ORDER BY t"""
    out = []
    for r in con.execute(sql, (venue, start, end)):
        n2 = r[2] or 0
        row = {
            "t": r[0], "samples": r[1], "two_sided_samples": n2, "coverage": min(1.0, r[1] / expected),
            "m1_spread_uptime": r[3], "spread_bps": r[4], "mid": r[-1],
            "m2": {f"d{b}": {"bid": r[5 + 2 * i], "ask": r[6 + 2 * i]} for i, b in enumerate((5, 10, 25))},
            "m3": {}, "m3_fill_rate": {},
        }
        for i, k in enumerate(("10k", "50k", "100k")):
            buy, sell = r[11 + 2 * i], r[12 + 2 * i]
            row["m3"][k] = {"buy": buy, "sell": sell}
            # share of two-sided samples where the visible book could fill the whole order
            row["m3_fill_rate"][k] = {"buy": (r[17 + 2 * i] / n2) if n2 else None,
                                      "sell": (r[18 + 2 * i] / n2) if n2 else None}
        out.append(row)
    return out


def book_window(con, venue: str, start: int, end: int) -> dict | None:
    """A single aggregate row for [start, end)."""
    ms = max(end - start, 1)
    expected = ms / (config.SAMPLE_SECONDS * 1000)
    sql = f"""
    SELECT COUNT(*), SUM(two_sided),
      AVG(CASE WHEN two_sided=1 AND spread_bps<={SPREAD_BPS} THEN 1.0 ELSE 0.0 END), AVG(spread_bps),
      AVG(bid_d5), AVG(ask_d5), AVG(bid_d10), AVG(ask_d10), AVG(bid_d25), AVG(ask_d25),
      AVG(buy_s10k), AVG(sell_s10k), AVG(buy_s50k), AVG(sell_s50k), AVG(buy_s100k), AVG(sell_s100k),
      COUNT(buy_s10k), COUNT(sell_s10k), COUNT(buy_s50k), COUNT(sell_s50k), COUNT(buy_s100k), COUNT(sell_s100k),
      AVG(mid), COUNT(bid_d5), COUNT(bid_d10), COUNT(bid_d25), COUNT(ask_d5), COUNT(ask_d10), COUNT(ask_d25)
    FROM book_samples WHERE venue=? AND ts>=? AND ts<?"""
    r = con.execute(sql, (venue, start, end)).fetchone()
    if not r or not r[0]:
        return None
    n, n2 = r[0], r[1] or 0
    return {
        "samples": n, "two_sided_samples": n2, "coverage": min(1.0, n / expected), "mid": r[22],
        "m1_spread_uptime": r[2], "spread_bps": r[3],
        "m2": {f"d{b}": {"bid": r[4 + 2 * i], "ask": r[5 + 2 * i], "n_bid": r[23 + i], "n_ask": r[26 + i]}
               for i, b in enumerate((5, 10, 25))},
        "m3": {k: {"buy": r[10 + 2 * i], "sell": r[11 + 2 * i],
                   "fill_rate_buy": (r[16 + 2 * i] / n2) if n2 else None,
                   "fill_rate_sell": (r[17 + 2 * i] / n2) if n2 else None}
               for i, k in enumerate(("10k", "50k", "100k"))},
    }


MINUTE = 60_000
_CANCEL = "CASE WHEN action='cancel' THEN -CAST(delta_size AS REAL) ELSE 0 END"
_FILL = "CASE WHEN action IN ('partial_fill','full_fill') THEN -CAST(delta_size AS REAL) ELSE 0 END"
_CANCEL_USD = "CASE WHEN action='cancel' THEN -CAST(delta_size AS REAL)*CAST(price AS REAL) ELSE 0 END"
_FILL_USD = "CASE WHEN action IN ('partial_fill','full_fill') THEN -CAST(delta_size AS REAL)*CAST(price AS REAL) ELSE 0 END"
_COLS = f"{_CANCEL}, {_FILL}, {_CANCEL_USD}, {_FILL_USD}, "         "CASE WHEN action='cancel' THEN 1 ELSE 0 END, CASE WHEN action IN ('partial_fill','full_fill') THEN 1 ELSE 0 END, "         "CASE WHEN action='open' THEN 1 ELSE 0 END"


def rollup_events(wcon, upto_ms: int | None = None, chunk_ms: int = 3_600_000) -> int:
    """Fold l3_events into per-minute rows older than 2 minutes. Idempotent; safe to run repeatedly."""
    from . import db
    now = db.now_ms()
    target = ((upto_ms if upto_ms is not None else now - 120_000) // MINUTE) * MINUTE
    done = db.get_meta(wcon, "events_rolled_until")
    if done is None:
        lo = wcon.execute("SELECT MIN(ts) FROM l3_events").fetchone()[0]
        if lo is None:
            return 0
        pos = (lo // MINUTE) * MINUTE
    else:
        pos = int(done)
    n = 0
    while pos < target:
        end = min(pos + chunk_ms, target)
        wcon.execute(f"""INSERT OR REPLACE INTO event_minute
          SELECT (ts/{MINUTE})*{MINUTE}, SUM({_CANCEL}), SUM({_FILL}), SUM({_CANCEL_USD}), SUM({_FILL_USD}),
                 SUM(CASE WHEN action='cancel' THEN 1 ELSE 0 END), SUM(CASE WHEN action IN ('partial_fill','full_fill') THEN 1 ELSE 0 END),
                 SUM(CASE WHEN action='open' THEN 1 ELSE 0 END)
          FROM l3_events WHERE ts>=? AND ts<? GROUP BY 1""", (pos, end))
        db.set_meta(wcon, "events_rolled_until", end)
        wcon.commit()
        pos = end
        n += 1
    return n


def _rolled(con) -> int:
    from . import db
    return int(db.get_meta(con, "events_rolled_until", 0) or 0)


def _event_union(step_ms: int, con, start: int, end: int):
    """Rollup rows below the rolled boundary R plus raw events above it, so results are always exact."""
    r = _rolled(con)
    mid = max(start, min(end, r))
    sql = f"""
    SELECT (t/{step_ms})*{step_ms} AS b, SUM(cancel_btc), SUM(fill_btc), SUM(cancel_usd), SUM(fill_usd), SUM(n_cancel), SUM(n_fill), SUM(n_open)
    FROM (
      SELECT t, cancel_btc, fill_btc, cancel_usd, fill_usd, n_cancel, n_fill, n_open FROM event_minute WHERE t>=? AND t<?
      UNION ALL
      SELECT (ts/{MINUTE})*{MINUTE}, {_CANCEL}, {_FILL}, {_CANCEL_USD}, {_FILL_USD},
             CASE WHEN action='cancel' THEN 1 ELSE 0 END, CASE WHEN action IN ('partial_fill','full_fill') THEN 1 ELSE 0 END,
             CASE WHEN action='open' THEN 1 ELSE 0 END
      FROM l3_events WHERE ts>=? AND ts<?
    ) GROUP BY b ORDER BY b"""
    return con.execute(sql, (start, mid, mid, end)).fetchall()


def _cf_row(t, r):
    c, f = r[1] or 0, r[2] or 0
    return {"t": t, "cancel_btc": c, "fill_btc": f, "cancel_usd": r[3] or 0, "fill_usd": r[4] or 0,
            "n_cancel": r[5] or 0, "n_fill": r[6] or 0, "n_open": r[7] or 0, "ratio": (c / f) if f else None}


def cancel_fill_series(con, step: str, start: int, end: int) -> list[dict]:
    ms = STEPS[step]
    start = (start // MINUTE) * MINUTE
    return [_cf_row(r[0], r) for r in _event_union(ms, con, start, end)]


def cancel_fill_window(con, start: int, end: int) -> dict:
    start = (start // MINUTE) * MINUTE
    rows = _event_union(10 ** 15, con, start, end)  # one giant bucket = whole window
    r = rows[0] if rows else (0, 0, 0, 0, 0, 0, 0, 0)
    d = _cf_row(0, r)
    d.pop("t")
    return d


def resilience(con, start: int, end: int, min_usd: float = 10_000, recover_to: float = 0.8,
               max_wait_ms: int = 600_000) -> dict:
    """M5. For every taker order above min_usd, time until depth within 10 bps on the side it hit is back to
    recover_to x its pre-trade level. Uses the 2 s book samples, so resolution is about 2 s."""
    takers = con.execute("""
      SELECT taker_order_id, MIN(ts), side, SUM(-CAST(delta_size AS REAL)*CAST(price AS REAL))
      FROM l3_events WHERE action IN ('partial_fill','full_fill') AND ts>=? AND ts<?
      GROUP BY taker_order_id HAVING SUM(-CAST(delta_size AS REAL)*CAST(price AS REAL)) >= ?""",
                         (start, end, min_usd)).fetchall()
    events = []
    for tid, ts, maker_side, usd in takers:
        col = "ask_d10" if maker_side == "sell" else "bid_d10"  # a taker buy consumes resting asks
        pre = con.execute(f"SELECT {col} FROM book_samples WHERE venue='strike' AND ts<=? AND ts>? ORDER BY ts DESC LIMIT 1",
                          (ts, ts - 10_000)).fetchone()
        if not pre or not pre[0]:
            continue
        target = pre[0] * recover_to
        rec = con.execute(f"SELECT ts FROM book_samples WHERE venue='strike' AND ts>? AND ts<=? AND {col}>=? ORDER BY ts LIMIT 1",
                          (ts, ts + max_wait_ms, target)).fetchone()
        events.append({"t": ts, "usd": usd, "side": "buy" if maker_side == "sell" else "sell", "pre_depth_usd": pre[0],
                       "recovery_ms": (rec[0] - ts) if rec else None})
    done = sorted(e["recovery_ms"] for e in events if e["recovery_ms"] is not None)
    return {"threshold_usd": min_usd, "recover_to": recover_to, "n_trades": len(events), "n_recovered": len(done),
            "median_recovery_ms": done[len(done) // 2] if done else None, "events": events[-50:]}


def coverage(con) -> dict:
    now_row = con.execute("SELECT MAX(ts) FROM book_samples").fetchone()[0]
    out = {}
    for v in VENUES:
        lo, hi, n = con.execute("SELECT MIN(ts),MAX(ts),COUNT(*) FROM book_samples WHERE venue=?", (v,)).fetchone()
        gaps = con.execute("SELECT COALESCE(SUM(COALESCE(end_ms,?)-start_ms),0), COUNT(*) FROM gaps WHERE venue=?",
                           (now_row or 0, v)).fetchone()
        span = (hi - lo) if lo else 0
        out[v] = {"first_ts": lo, "last_ts": hi, "samples": n, "span_hours": span / 3.6e6,
                  "expected_samples": span / (config.SAMPLE_SECONDS * 1000),
                  "sample_coverage": (n / (span / (config.SAMPLE_SECONDS * 1000))) if span else None,
                  "gap_ms": gaps[0], "gap_count": gaps[1]}
    from . import db as _db
    import json as _json
    st = _db.get_meta(con, "l3_stats")
    if st:
        d = _json.loads(st)
        ev = (d["count"], d["first_ts"], d["last_ts"])
    else:
        ev = con.execute("SELECT COUNT(*),MIN(ts),MAX(ts) FROM l3_events").fetchone()
    out["l3_events"] = {"count": ev[0], "first_ts": ev[1], "last_ts": ev[2]}
    return out


def flow_toxicity(con, start: int, end: int, horizon_ms: int = 10_000) -> dict:
    """M6. Mid-price move over `horizon_ms` after every taker order, signed in the taker's direction, averaged.
    Positive = price kept moving the taker's way (the resting side was picked off); negative = price reverted.
    Mid comes from the burst-aware 2 s Strike samples: the last one at or before the trade and the first one at or
    after trade time + horizon."""
    takers = con.execute("""
      SELECT taker_order_id, MIN(ts), side FROM l3_events
      WHERE action IN ('partial_fill','full_fill') AND ts>=? AND ts<? GROUP BY taker_order_id""", (start, end)).fetchall()
    moves = []
    for _tid, ts, maker_side in takers:
        pre = con.execute("SELECT mid FROM book_samples WHERE venue='strike' AND two_sided=1 AND ts<=? AND ts>? ORDER BY ts DESC LIMIT 1",
                          (ts, ts - 6000)).fetchone()
        post = con.execute("SELECT mid FROM book_samples WHERE venue='strike' AND two_sided=1 AND ts>=? AND ts<=? ORDER BY ts LIMIT 1",
                           (ts + horizon_ms, ts + horizon_ms + 6000)).fetchone()
        if not pre or not post or not pre[0]:
            continue
        sign = 1 if maker_side == "sell" else -1  # a taker buy lifts a resting sell
        moves.append((ts, sign * (post[0] - pre[0]) / pre[0] * 1e4))
    if not moves:
        return {"horizon_ms": horizon_ms, "n_takers": len(takers), "n_measured": 0, "mean_bps": None, "median_bps": None,
                "share_continued": None, "hourly": []}
    vals = sorted(m for _, m in moves)
    hourly = {}
    for ts, m in moves:
        hourly.setdefault((ts // STEPS["hour"]) * STEPS["hour"], []).append(m)
    return {"horizon_ms": horizon_ms, "n_takers": len(takers), "n_measured": len(moves),
            "mean_bps": sum(vals) / len(vals), "median_bps": vals[len(vals) // 2],
            "share_continued": sum(1 for v in vals if v > 0) / len(vals),
            "hourly": [{"t": t, "mean_bps": sum(v) / len(v), "n": len(v)} for t, v in sorted(hourly.items())]}
