"""Zetaris SQL client, written against Zetaris' own OpenAPI spec (docs/zetaris-openapi.yaml, from api.saas.enterprise.zetaris.com/redoc).

Flow from the spec and their "Accessing Zetaris using API" article: GET /api/v1.0/auth/login (Basic auth + X-Org-ID + X-Request-ID) returns idToken and
refreshToken; every other call needs X-Org-ID, X-Request-ID and a Bearer token. SQL runs as POST /api/v1.0/query/sql/start {select, pageLimit<=100} ->
GET /api/v1.0/query/sql/page -> DELETE /api/v1.0/query/sql/close/{queryToken}.

Nothing here runs unless ZETARIS_ORG_ID, ZETARIS_USERNAME, ZETARIS_PASSWORD and ZETARIS_SAMPLES_TABLE are set (ZETARIS_API_KEY is optional), so the agent never pretends to have used it.
Env: ZETARIS_BASE_URL (default https://api.saas.enterprise.zetaris.com), ZETARIS_SAMPLES_TABLE (the table holding Follow's book_samples Parquet).
"""
import os
import re
import time
import uuid

import httpx

BASE = lambda: os.environ.get("ZETARIS_BASE_URL") or "https://api.saas.enterprise.zetaris.com"  # noqa: E731
_token = {"id": None, "at": 0.0}


def configured() -> bool:
    # ZETARIS_API_KEY is optional: the SaaS console issues one, a local install does not (the login idToken is the Bearer there)
    return all(os.environ.get(k) for k in ("ZETARIS_ORG_ID", "ZETARIS_USERNAME", "ZETARIS_PASSWORD", "ZETARIS_SAMPLES_TABLE"))


def _headers(bearer: str | None = None) -> dict:
    h = {"X-Request-ID": str(uuid.uuid4()), "X-Org-ID": os.environ["ZETARIS_ORG_ID"]}
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


def login() -> str:
    """Returns the idToken (cached for 10 minutes)."""
    if _token["id"] and time.time() - _token["at"] < 600:
        return _token["id"]
    r = httpx.get(BASE() + "/api/v1.0/auth/login", headers=_headers(), auth=(os.environ["ZETARIS_USERNAME"], os.environ["ZETARIS_PASSWORD"]), timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"zetaris login {r.status_code}: {r.text[:200]}")
    _token["id"], _token["at"] = r.json()["idToken"], time.time()
    return _token["id"]


def _call(method: str, path: str, **kw):
    """The article says the Bearer is the API key; if the server wants the login idToken instead, retry once with it."""
    last = None
    for bearer in ([os.environ["ZETARIS_API_KEY"]] if os.environ.get("ZETARIS_API_KEY") else []) + [None]:
        tok = bearer or login()
        r = httpx.request(method, BASE() + path, headers=_headers(tok), timeout=60, **kw)
        if r.status_code not in (401, 403):
            if r.status_code >= 400:
                raise RuntimeError(f"zetaris {method} {path} -> {r.status_code}: {r.text[:240]}")
            return r
        last = r
    raise RuntimeError(f"zetaris auth rejected ({last.status_code}): {last.text[:200]}")


def query(sql: str, max_rows: int = 200) -> dict:
    """Run one SQL statement and return its rows. Always closes the query token."""
    start = _call("POST", "/api/v1.0/query/sql/start", json={"select": sql, "pageLimit": min(100, max_rows)}).json()
    token = start["queryToken"]
    rows = list(start.get("records") or [])
    try:
        page = 2
        while len(rows) < max_rows and page <= int(start.get("totalPages") or 1):
            p = _call("GET", "/api/v1.0/query/sql/page", params={"queryToken": token, "pageLimit": min(100, max_rows), "pageNumber": page}).json()
            rows += p.get("records") or []
            page += 1
    finally:
        try:
            _call("DELETE", f"/api/v1.0/query/sql/close/{token}")
        except Exception:  # noqa: BLE001
            pass
    return {"sql": sql, "total_count": start.get("totalCount"), "rows": rows[:max_rows]}


# ------------------------------------------------------------------ the agent tool: a fixed, parameterised query (the model never writes SQL)
def depth_summary_sql(table: str, venue: str, start_ms: int, end_ms: int) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.]+", table):
        raise ValueError("bad table name")
    if venue not in ("strike", "binance", "hyperliquid"):
        raise ValueError("bad venue")
    return (f"SELECT COUNT(*) AS samples, AVG(spread_bps) AS avg_spread_bps, MIN(spread_bps) AS min_spread_bps, MAX(spread_bps) AS max_spread_bps, "
            f"AVG((bid_d10 + ask_d10) / 2) AS avg_depth10_usd, MIN((bid_d10 + ask_d10) / 2) AS min_depth10_usd, "
            f"AVG((buy_s50k + sell_s50k) / 2) AS avg_slippage_50k_bps "
            f"FROM {table} WHERE venue = '{venue}' AND two_sided = 1 AND ts >= {int(start_ms)} AND ts < {int(end_ms)}")


def depth_summary(venue: str, start_ms: int, end_ms: int) -> dict:
    return query(depth_summary_sql(os.environ["ZETARIS_SAMPLES_TABLE"], venue, start_ms, end_ms), max_rows=5)
