"""Read-only HTTP API over the recorded store. Run: python -m follow.api"""
import json
import os
import threading
import time

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import config, db, designer, export, metrics

app = FastAPI(title="Follow API", version="1.0",
              description="Strike BTC-USD liquidity scorecard. Read-only; all values computed from recorded public feeds.")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])

_local = threading.local()


def con():
    c = getattr(_local, "con", None)
    if c is None:
        c = _local.con = db.connect(config.DB_PATH, readonly=True)
    return c


def parse_step(step: str):
    if step not in metrics.STEPS:
        raise HTTPException(400, f"step must be one of {list(metrics.STEPS)}")
    return step


@app.get("/", include_in_schema=False)
def root():
    """The tunnel URL is the API, not the website: send browsers to the live scorecard."""
    url = os.environ.get("FRONTEND_URL")
    if not url:
        return {"name": "Follow API", "docs": "/docs", "health": "/api/health"}
    return RedirectResponse(url, status_code=307)


@app.get("/api/health")
def health():
    c = con()
    now = db.now_ms()
    if config.SNAPSHOT_MODE:
        return {"now": now, "ok": True, "mode": "snapshot", "as_of": int(db.get_meta(c, "snapshot_as_of", 0) or 0), "feeds": {}}
    feeds = {}
    for v in ("strike", "binance", "hyperliquid", "strike_market"):
        hb = db.get_meta(c, f"heartbeat:{v}")
        feeds[v] = {"heartbeat_age_s": (now - int(hb)) / 1000 if hb else None, "ok": bool(hb) and now - int(hb) < 30_000}
    return {"now": now, "feeds": feeds, "ok": all(f["ok"] for f in feeds.values())}


@app.get("/api/latest")
def latest():
    """Most recent book sample per venue (what the landing page widget shows)."""
    c = con()
    out = {}
    for v in metrics.VENUES:
        r = c.execute("SELECT ts,mid,spread_bps,buy_s10k,sell_s10k,buy_s50k,sell_s50k,buy_s100k,sell_s100k "
                      "FROM book_samples WHERE venue=? AND two_sided=1 ORDER BY ts DESC LIMIT 1", (v,)).fetchone()
        if r:
            out[v] = dict(zip(("ts", "mid", "spread_bps", "buy_10k", "sell_10k", "buy_50k", "sell_50k", "buy_100k", "sell_100k"), r))
    return out


@app.get("/api/book")
def book():
    """Latest recorded Strike L3 book as aggregated levels (used to draw the depth artwork)."""
    raw = db.get_meta(con(), "strike_latest_book")
    if not raw:
        raise HTTPException(503, "no book recorded yet")
    b = json.loads(raw)
    return {"ts": b["ts"], "seq": b["seq"], "bids": b["bids"][:200], "asks": b["asks"][:200]}


@app.get("/api/coverage")
def coverage():
    return metrics.coverage(con())


@app.get("/api/gaps")
def gaps(limit: int = 200):
    rows = con().execute("SELECT id,venue,start_ms,end_ms,reason,last_sequence FROM gaps ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(zip(("id", "venue", "start_ms", "end_ms", "reason", "last_sequence"), r)) for r in rows]


@app.get("/api/scorecard")
def scorecard(window_minutes: int = Query(60, ge=1, le=60 * 24 * 14), compare: str = Query("prev", pattern="^(prev|day|week)$")):
    """Latest window plus the window immediately before it, for every venue; M4 for Strike."""
    c = con()
    last = c.execute("SELECT MAX(ts) FROM book_samples").fetchone()[0]
    if not last:
        raise HTTPException(503, "no data recorded yet")
    w = window_minutes * 60_000
    end, mid = last + 1, last + 1 - w
    # the comparison window: the one right before, or the same window 24 h / 7 days earlier (needs that much history)
    shift = {"prev": w, "day": 86_400_000, "week": 7 * 86_400_000}[compare]
    pstart, pend = mid - shift, end - shift
    first_any = c.execute("SELECT MIN(ts) FROM book_samples WHERE venue='strike'").fetchone()[0]
    has_history = first_any is not None and pstart >= first_any - 60_000
    out = {"as_of": last, "window_minutes": window_minutes, "compare": compare, "compare_available": has_history, "venues": {}}
    for v in metrics.VENUES:
        out["venues"][v] = {"current": metrics.book_window(c, v, mid, end),
                            "previous": metrics.book_window(c, v, pstart, pend) if has_history else None}
    out["m4_strike"] = {"current": metrics.cancel_fill_window(c, mid, end),
                        "previous": metrics.cancel_fill_window(c, pstart, pend) if has_history else None}
    first = c.execute("SELECT MIN(ts) FROM book_samples WHERE venue='strike'").fetchone()[0]
    out["since_start"] = {v: metrics.book_window(c, v, first, end) for v in metrics.VENUES}
    out["m4_since_start"] = metrics.cancel_fill_window(c, first, end)
    mk = json.loads(db.get_meta(c, "binance_markets", "[]"))
    fb = c.execute("SELECT MIN(ts) FROM book_samples WHERE venue='binance'").fetchone()[0]
    if fb and (not mk or mk[0][0] > fb):  # switches were only logged later; before that it was the perpetual
        mk = [[fb, "futures"]] + mk
    out["binance_markets"] = mk
    out["notes"] = [
        "Binance is the USD-M perpetual BTCUSDT when reachable, otherwise Binance's public spot BTCUSDT mirror; the markets used and when are in binance_markets. "
        "Venue differences: Strike is read from the full L3 book. Binance (futures BTCUSDT) is a 1000-level local book, "
        "Hyperliquid BTC is the top 20 levels per side at two price granularities; bands outside a feed's reach are n/a.",
    ]
    return out


@app.get("/api/series")
def series(venue: str = "strike", step: str = "minute", start: int | None = None, end: int | None = None,
           hours: float = 6):
    if venue not in metrics.VENUES:
        raise HTTPException(400, f"venue must be one of {list(metrics.VENUES)}")
    parse_step(step)
    c = con()
    last = c.execute("SELECT MAX(ts) FROM book_samples").fetchone()[0] or db.now_ms()
    end = end or last + 1
    start = start or end - int(hours * 3_600_000)
    if (end - start) / metrics.STEPS[step] > 20_000:
        raise HTTPException(400, "range too large for this step")
    return {"venue": venue, "step": step, "start": start, "end": end, "points": metrics.book_series(c, venue, step, start, end)}


@app.get("/api/query")
def query(start: int, end: int, step: str = "minute", venues: str = "strike,binance,hyperliquid"):
    """Metric values for a time range (unix ms), the read-only endpoint from the PRD."""
    parse_step(step)
    if (end - start) / metrics.STEPS[step] > 20_000:
        raise HTTPException(400, "range too large for this step")
    c = con()
    res = {}
    for v in venues.split(","):
        if v not in metrics.VENUES:
            raise HTTPException(400, f"unknown venue {v}")
        res[v] = metrics.book_series(c, v, step, start, end)
    res["m4_strike"] = metrics.cancel_fill_series(c, step, start, end)
    return {"start": start, "end": end, "step": step, "data": res}


@app.get("/api/cancel_fill")
def cancel_fill(step: str = "hour", hours: float = 24):
    parse_step(step)
    c = con()
    last = c.execute("SELECT MAX(ts) FROM l3_events").fetchone()[0] or db.now_ms()
    return {"step": step, "points": metrics.cancel_fill_series(c, step, last - int(hours * 3_600_000), last + 1)}


@app.get("/api/resilience")
def resilience(hours: float = 48, min_usd: float = 10_000):
    c = con()
    last = c.execute("SELECT MAX(ts) FROM l3_events").fetchone()[0] or db.now_ms()
    return metrics.resilience(c, last - int(hours * 3_600_000), last + 1, min_usd=min_usd)


@app.get("/api/toxicity")
def toxicity(hours: float = 48, horizon_s: int = Query(10, ge=1, le=60)):
    c = con()
    last = c.execute("SELECT MAX(ts) FROM l3_events").fetchone()[0] or db.now_ms()
    return metrics.flow_toxicity(c, last - int(hours * 3_600_000), last + 1, horizon_s * 1000)


@app.get("/api/alerts")
def alerts(limit: int = 50):
    rows = con().execute("SELECT id,ts,venue,kind,message FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(zip(("id", "ts", "venue", "kind", "message"), r)) for r in rows]


class DesignerIn(BaseModel):
    rebate_bps: float = Field(ge=0, le=100)
    n_quoters: int = Field(ge=0, le=1000)
    quote_size_usd: float = Field(ge=0, le=100_000_000)
    adverse_selection_bps: float = Field(1.5, gt=0, le=100)
    turnover_per_day: float = Field(1.0, ge=0, le=1000)


@app.post("/api/designer")
def designer_run(body: DesignerIn):
    try:
        return designer.run(con(), **body.model_dump())
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


class AskIn(BaseModel):
    question: str = Field(min_length=5, max_length=400)


_ask_log: dict[str, list[float]] = {}


@app.post("/api/ask")
def ask_follow(body: AskIn, request: Request):
    """Ask Follow: a tool-calling agent that answers from the recorded data and returns the evidence for every number."""
    from . import agent
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    now = time.time()
    recent = [t for t in _ask_log.get(ip, []) if now - t < 3600]
    if len(recent) >= 12:
        raise HTTPException(429, "limit: 12 questions per hour")
    _ask_log[ip] = recent + [now]
    if not agent.backend():
        raise HTTPException(503, "the agent has no model key configured on this server")
    try:
        return agent.ask(body.question)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"agent failed: {str(e)[:200]}") from e


@app.get("/api/dataset")
def dataset_list():
    return {"files": export.list_files(), "schema": "/api/dataset/schema"}


@app.get("/api/dataset/schema")
def dataset_schema():
    return FileResponse(export.SCHEMA_README, media_type="text/markdown")


@app.get("/api/dataset/{name}")
def dataset_file(name: str):
    path = export.resolve(name)
    if not path:
        raise HTTPException(404, "no such file")
    return FileResponse(path, filename=os.path.basename(path))


def _export_loop():
    while True:
        try:
            export.build_all()
        except Exception as e:  # noqa: BLE001
            print("export failed:", repr(e))
        time.sleep(900)


def _alert_loop():
    """Alert when a feed heartbeat goes stale and again when it recovers. Always stored; POSTed if a webhook is set."""
    import httpx
    wcon = db.connect(config.DB_PATH)
    stale = {}
    while True:
        try:
            now = db.now_ms()
            for v in ("strike", "binance", "hyperliquid", "strike_market"):
                hb = db.get_meta(wcon, f"heartbeat:{v}")
                if not hb:
                    continue
                age = (now - int(hb)) / 1000
                is_stale = age > config.ALERT_STALE_SECONDS
                if is_stale != stale.get(v, False):
                    stale[v] = is_stale
                    kind = "stale" if is_stale else "recovered"
                    msg = f"{v} feed heartbeat is {age:.0f}s old" if is_stale else f"{v} feed is recording again"
                    delivered = 0
                    if config.ALERT_WEBHOOK_URL:
                        try:
                            body = {"content": f"Follow: {msg}", "text": f"Follow: {msg}"}
                            delivered = int(httpx.post(config.ALERT_WEBHOOK_URL, json=body, timeout=8).status_code < 300)
                        except Exception:  # noqa: BLE001
                            delivered = 0
                    wcon.execute("INSERT INTO alerts(ts,venue,kind,message,delivered) VALUES(?,?,?,?,?)", (now, v, kind, msg, delivered))
                    wcon.commit()
        except Exception as e:  # noqa: BLE001
            print("alert loop error:", repr(e))
        time.sleep(15)


def _rollup_loop():
    wcon = db.connect(config.DB_PATH)  # also creates any missing tables
    while True:
        try:
            metrics.rollup_events(wcon)
        except Exception as e:  # noqa: BLE001
            print("rollup failed:", repr(e))
        time.sleep(30)


@app.on_event("startup")
def _startup():
    db.connect(config.DB_PATH).close()  # make sure tables exist before readers query them
    if not config.SNAPSHOT_MODE:  # a snapshot has no live feeds: no rollup writer, no stale-feed alerts
        threading.Thread(target=_rollup_loop, daemon=True).start()
        threading.Thread(target=_alert_loop, daemon=True).start()
    threading.Thread(target=_export_loop, daemon=True).start()


def main():
    import uvicorn
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)


if __name__ == "__main__":
    main()
