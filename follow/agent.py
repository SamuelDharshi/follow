"""Ask Follow: a tool-calling investigator agent over the recorded liquidity data.

The model never sees SQL. Its tools are the same functions that sit behind the HTTP API. It plans, calls at most MAX_CALLS tools, then
answers in JSON. Code, not the model, enforces the honesty rule: every claim must match a number that a tool actually returned, and any
number in the answer without a surviving claim is removed.

Model backends (first configured wins): NVIDIA_API_KEY -> Nemotron via https://integrate.api.nvidia.com/v1 (OpenAI-compatible),
OPENAI_API_KEY + AGENT_BASE_URL, ANTHROPIC_API_KEY -> Claude. Keys stay server-side.
"""
import json
import os
import re
import time

import httpx

from . import config, db

MAX_CALLS = 6

TOOLS = {
    "coverage": {"d": "Recorded coverage per venue: first/last timestamp (unix ms), hours, gap time. Call first to learn what time range exists.", "p": {}},
    "scorecard": {"d": "Latest window (and a comparison window) of M1 spread uptime, M2 depth, M3 slippage for strike, binance, hyperliquid, plus Strike cancel/fill.",
                  "p": {"window_minutes": "int 1..20160, default 60", "compare": "prev | day | week"}},
    "series": {"d": "Time series of M1-M3 for one venue between start and end (unix ms), bucketed.",
               "p": {"venue": "strike | binance | hyperliquid", "step": "minute | hour | day", "start": "unix ms", "end": "unix ms"}},
    "gaps": {"d": "Recording gaps (outages) per venue with start, end and reason. Use to check whether a window is affected.", "p": {"limit": "int, default 60"}},
    "resilience": {"d": "M5: recovery time of depth within 10 bps after taker orders above a USD threshold.", "p": {"hours": "number", "min_usd": "number"}},
    "toxicity": {"d": "M6: average mid-price move in the taker's direction after taker orders.", "p": {"hours": "number", "horizon_s": "1..60"}},
    "cancel_fill": {"d": "Strike placed/cancelled/filled counts and cancel/fill ratio per bucket.", "p": {"step": "minute | hour | day", "hours": "number"}},
}


def tools() -> dict:
    t = dict(TOOLS)
    from . import zetaris
    if zetaris.configured():
        t["zetaris_depth_summary"] = {"d": "Summary of one venue's book samples over a window (sample count, average/min/max spread, average/min depth within 10 bps, average $50k slippage), computed by a SQL query "
                                      "that runs inside Zetaris over the Parquet export. Use it to cross-check scorecard/series numbers.",
                                      "p": {"venue": "strike | binance | hyperliquid", "start": "unix ms", "end": "unix ms"}}
    return t


# ----------------------------------------------------------------------------- tool execution (existing API functions)
def run_tool(name: str, args: dict):
    from . import api  # imported lazily: the API module owns the DB connection helpers
    if name == "coverage":
        return api.coverage()
    if name == "scorecard":
        return api.scorecard(window_minutes=int(args.get("window_minutes", 60)), compare=str(args.get("compare", "prev")))
    if name == "series":
        start, end = int(args["start"]), int(args["end"])
        return api.series(venue=str(args["venue"]), step=str(args.get("step", "hour")), start=start, end=end, hours=6)
    if name == "gaps":
        return api.gaps(limit=int(args.get("limit", 60)))
    if name == "resilience":
        return api.resilience(hours=float(args.get("hours", 48)), min_usd=float(args.get("min_usd", 10000)))
    if name == "toxicity":
        return api.toxicity(hours=float(args.get("hours", 48)), horizon_s=int(args.get("horizon_s", 10)))
    if name == "cancel_fill":
        return api.cancel_fill(step=str(args.get("step", "hour")), hours=float(args.get("hours", 24)))
    if name == "zetaris_depth_summary":
        from . import zetaris
        return zetaris.depth_summary(str(args["venue"]), int(args["start"]), int(args["end"]))
    raise ValueError(f"unknown tool {name}")


def _compact(x, depth=0):
    """Shrink a tool result for the model: round floats, cap list lengths (the full result is still used to verify claims)."""
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: _compact(v, depth + 1) for k, v in x.items() if k not in ("events",)}
    if isinstance(x, list):
        if len(x) > 40:
            step = len(x) / 40
            x = [x[int(i * step)] for i in range(40)]
        return [_compact(v, depth + 1) for v in x]
    return x


# ----------------------------------------------------------------------------- model backends
def backend():
    if os.environ.get("NVIDIA_API_KEY"):
        return {"kind": "openai", "base": "https://integrate.api.nvidia.com/v1", "key": os.environ["NVIDIA_API_KEY"],
                "model": os.environ.get("AGENT_MODEL") or "nvidia/nemotron-3.5-lightning-30b-a3b"}
    if os.environ.get("OPENAI_API_KEY") and os.environ.get("AGENT_BASE_URL"):
        return {"kind": "openai", "base": os.environ["AGENT_BASE_URL"], "key": os.environ["OPENAI_API_KEY"], "model": os.environ.get("AGENT_MODEL") or "gpt-4o-mini"}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"kind": "anthropic", "key": os.environ["ANTHROPIC_API_KEY"], "model": os.environ.get("AGENT_MODEL") or "claude-haiku-4-5"}
    return None


def _schema():
    out = []
    for n, t in tools().items():
        props = {k: {"type": "string", "description": v} for k, v in t["p"].items()}
        out.append((n, t["d"], {"type": "object", "properties": props, "required": []}))
    return out


def _openai_turn(b, messages, allow_tools):
    body = {"model": b["model"], "messages": messages, "temperature": 0.1, "max_tokens": 1800}
    if "nvidia.com" in b["base"]:
        body["chat_template_kwargs"] = {"enable_thinking": False}  # thinking mode spends the token budget on hidden reasoning and is slow
    if allow_tools:
        body["tools"] = [{"type": "function", "function": {"name": n, "description": d, "parameters": s}} for n, d, s in _schema()]
        body["tool_choice"] = "auto"
    r = httpx.post(b["base"] + "/chat/completions", headers={"Authorization": f"Bearer {b['key']}"}, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"model API {r.status_code}: {r.text[:300]}")
    m = r.json()["choices"][0]["message"]
    calls = [{"id": c["id"], "name": c["function"]["name"], "args": json.loads(c["function"]["arguments"] or "{}")} for c in (m.get("tool_calls") or [])]
    return m.get("content") or "", calls, m


def _anthropic_turn(b, system, messages, allow_tools):
    body = {"model": b["model"], "max_tokens": 1800, "system": system, "messages": messages, "temperature": 0.1}
    if allow_tools:
        body["tools"] = [{"name": n, "description": d, "input_schema": s} for n, d, s in _schema()]
    r = httpx.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": b["key"], "anthropic-version": "2023-06-01"}, json=body, timeout=60)
    r.raise_for_status()
    blocks = r.json()["content"]
    text = "".join(x.get("text", "") for x in blocks if x["type"] == "text")
    calls = [{"id": x["id"], "name": x["name"], "args": x["input"]} for x in blocks if x["type"] == "tool_use"]
    return text, calls, blocks


# ----------------------------------------------------------------------------- honesty enforcement
_NUM = re.compile(r"(?<![\w.])\$?-?\d[\d,]*\.?\d*\s?(?:k|K|M|m|bps|%|x|×)?")
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"


def _to_num(tok: str):
    t = tok.replace("$", "").replace(",", "").strip().lower()
    mult = 1.0
    for suf, m in (("bps", 1.0), ("%", 1.0), ("x", 1.0), ("×", 1.0), ("k", 1e3), ("m", 1e6)):
        if t.endswith(suf):
            t, mult = t[: -len(suf)].strip(), m
            break
    try:
        return float(t) * mult
    except ValueError:
        return None


def numbers_in(text: str) -> list[float]:
    cleaned = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", text)                      # clock times
    cleaned = re.sub(rf"\b{_MONTHS}\.?\s+\d{{1,2}}\b|\b\d{{1,2}}\s+{_MONTHS}\b", " ", cleaned, flags=re.I)  # dates
    cleaned = re.sub(r"\b20\d\d\b", " ", cleaned)                                       # years
    out = []
    for m in _NUM.finditer(cleaned):
        v = _to_num(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, 0.012 * max(abs(a), abs(b)))


def _walk_numbers(x, acc):
    if isinstance(x, bool):
        return
    if isinstance(x, (int, float)):
        acc.append(float(x))
    elif isinstance(x, dict):
        for v in x.values():
            _walk_numbers(v, acc)
    elif isinstance(x, list):
        for v in x:
            _walk_numbers(v, acc)


def _derived(nums: list[float]) -> list[float]:
    """Values a tool result implies by simple scaling: fractions shown as %, USD shown as k/M, bps."""
    out = []
    for n in nums:
        out.append(n)
        out.append(n * 100)        # 0.9959 -> 99.59%
        out.append(abs(n))
        out.append(n / 1000)       # 948 ms -> 0.948 s
        out.append(n * 1000)
    return out


def verify(claims: list[dict], calls: list[dict]) -> list[dict]:
    """Keep only claims whose value (or a number in its text) is found in the result of the tool call they cite."""
    kept = []
    for c in claims:
        src = [x for x in calls if x["name"] == c.get("tool")]
        if not src:
            continue
        pool = []
        for call in src:
            _walk_numbers(call["result"], pool)
        pool = _derived(pool)
        wanted = []
        v = c.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            wanted.append(float(v))
        elif isinstance(v, str):
            wanted += numbers_in(v)
        if not wanted:
            wanted = numbers_in(c.get("text", ""))
        if wanted and all(any(_close(w, p) for p in pool) for w in wanted[:2]):
            c = dict(c)
            c["call_id"] = src[-1]["id"]
            c["window"] = _window_of(src[-1])
            kept.append(c)
    return kept


def _window_of(call: dict):
    a = call["args"]
    if "start" in a and "end" in a:
        return {"start": int(a["start"]), "end": int(a["end"])}
    r = call["result"]
    if call["name"] == "scorecard" and isinstance(r, dict) and r.get("as_of"):
        return {"start": int(r["as_of"]) - int(a.get("window_minutes", 60)) * 60000, "end": int(r["as_of"])}
    h = a.get("hours")
    if h:
        end = db.now_ms()
        return {"start": end - int(float(h) * 3_600_000), "end": end}
    return None


def strip_unbacked(answer: str, claims: list[dict], allowed: list[float] | None = None) -> tuple[str, int]:
    """Remove every sentence that contains a number no surviving claim supports. `allowed` = numbers the user asked about (not facts)."""
    backed = list(allowed or [])
    for c in claims:
        if isinstance(c.get("value"), (int, float)):
            backed += [float(c["value"]), float(c["value"]) * 100]
        backed += numbers_in(c.get("text", ""))
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    keep, dropped = [], 0
    for s in sentences:
        bad = [n for n in numbers_in(s) if not any(_close(n, b) for b in backed)]
        if bad:
            dropped += 1
        else:
            keep.append(s)
    return " ".join(keep), dropped


def gaps_affecting(claims: list[dict], gaps: list[dict]) -> list[dict]:
    out, seen = [], set()
    for c in claims:
        w = c.get("window")
        if not w:
            continue
        for g in gaps:
            gs, ge = g["start_ms"], g["end_ms"] or db.now_ms()
            if g["id"] not in seen and gs < w["end"] and ge > w["start"]:
                seen.add(g["id"])
                out.append({"venue": g["venue"], "start_ms": gs, "end_ms": g["end_ms"], "reason": g["reason"], "minutes": round((ge - gs) / 60000, 1)})
    return sorted(out, key=lambda g: -g["minutes"])[:8]


# ----------------------------------------------------------------------------- memory (H-MEM-shaped, see follow/hmem.py)
def _recall(question: str, n=4):
    from . import hmem
    try:
        return hmem.recall(question, k=n)
    except Exception:  # noqa: BLE001
        return []


def _remember(q, result):
    """Store each verified claim as a record with its source and provenance (tool, args, call id). Unverified text is never stored."""
    from . import hmem
    try:
        for c in result["claims"][:6]:
            tags = [c["tool"]] + ([str(c["args"]["venue"])] if isinstance(c.get("args"), dict) and c["args"].get("venue") else [])
            hmem.add(f"{c['text']} (value {c.get('value')})", source="follow-agent", confidence={"high": 0.9, "medium": 0.7, "low": 0.5}.get(result["confidence"], 0.6),
                     provenance={"question": q, "tool": c["tool"], "args": c.get("args"), "call_id": c.get("call_id"), "window": c.get("window"), "model": result["model"]},
                     tags=tags)
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- the loop
SYSTEM = """You are Follow, an analyst for Strike's BTC-USD liquidity. You answer ONLY from tool results; you have no other source of numbers.
Data: Strike (full L3 book), Binance and Hyperliquid BTC, recorded live. Data covers {first} to {last} (unix ms now={now}); the recorder has gaps.
Metrics: M1 spread uptime (share of time two-sided and spread <= 5 bps), M2 depth within N bps (USD per side), M3 slippage in bps for $10k/$50k/$100k market orders,
M4 cancel/fill, M5 depth resilience, M6 flow toxicity.
Method: the time range is above, so do NOT call `coverage` or `gaps` (code already checks every window against the gap table). Decide which tools you need and request them ALL IN ONE STEP
(parallel calls), at most {max_calls} in total; then answer. Choose tools for the question: depth recovery -> resilience; do takers move price -> toxicity; Strike vs Binance -> scorecard
(and series for 'yesterday'/'last N hours'); change over time -> series. For "yesterday" or "last N hours" compute start/end in unix ms from the data end time above; series buckets: minute for <=6 h, hour for <=7 d, day otherwise.
Final message must be ONLY this JSON, no prose around it:
{{"answer": "2-5 sentences", "claims": [{{"text": "short statement", "tool": "<tool name used>", "args": {{}}, "value": <the single number from that tool result>}}],
 "gaps_affecting_answer": ["plain-language gap notes"], "confidence": "high|medium|low"}}
Rules: every number in `answer` must also appear as the `value` (or in the text) of a claim, copied from a tool result. Do not compute new numbers except
simple ratios you list as their own claim with tool "scorecard"/"series" and the ratio as value only if both inputs are claims. Never write unix timestamps or raw times; say
"yesterday" or "the last hour". If a gap overlaps the window, say so and lower the confidence. If the data cannot answer, say so; never guess.
{memory}"""


def _extract_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def ask(question: str) -> dict:
    b = backend()
    if not b:
        raise RuntimeError("no model key configured (set NVIDIA_API_KEY for Nemotron, or ANTHROPIC_API_KEY)")
    t0 = time.time()
    cov = run_tool("coverage", {})
    first, last = cov["strike"]["first_ts"], cov["strike"]["last_ts"]
    now = last if config.SNAPSHOT_MODE else db.now_ms()
    mem = _recall(question)
    memtxt = ("Memory (verified earlier findings; use only for follow-ups such as 'better than your last answer', "
              "and re-check with tools before reusing a number):" + chr(10) +
              chr(10).join(f"- [{round((db.now_ms() - m['timestamp']) / 3.6e6, 1)} h ago, confidence {m['confidence']}] {m['content']}" for m in mem)) if mem else ""
    system = SYSTEM.format(first=first, last=last, now=now, max_calls=MAX_CALLS, memory=memtxt)
    calls = [{"id": "c0", "name": "coverage", "args": {}, "result": cov}]
    messages = [{"role": "user", "content": question}]
    oa = [{"role": "system", "content": system}] + messages
    final_text = ""
    for turn in range(MAX_CALLS + 2):
        allow = len(calls) - 1 < MAX_CALLS and turn < MAX_CALLS + 1
        if b["kind"] == "openai":
            text, tcs, raw = _openai_turn(b, oa, allow)
        else:
            text, tcs, raw = _anthropic_turn(b, system, messages, allow)
        if not tcs:
            final_text = text
            break
        results = []
        for tc in tcs:
            if len(calls) - 1 >= MAX_CALLS:
                res = {"error": "tool budget used up; answer now"}
            else:
                try:
                    res = run_tool(tc["name"], tc["args"])
                except Exception as e:  # noqa: BLE001
                    res = {"error": str(e)[:200]}
            calls.append({"id": f"c{len(calls)}", "name": tc["name"], "args": tc["args"], "result": res})
            results.append((tc, res))
        if b["kind"] == "openai":
            oa.append(raw)
            for tc, res in results:
                oa.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(_compact(res))[:9000]})
        else:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tc["id"], "content": json.dumps(_compact(res))[:9000]} for tc, res in results]})
    parsed = _extract_json(final_text)
    if parsed is None and final_text.strip():  # one repair attempt: ask the model to re-emit its answer as the required JSON only
        fix = [{"role": "system", "content": system}, {"role": "user", "content": "Re-emit this as ONLY the required JSON object, unchanged in meaning:" + chr(10) + final_text[:4000]}]
        try:
            parsed = _extract_json(_openai_turn(b, fix, False)[0] if b["kind"] == "openai" else _anthropic_turn(b, system, fix[1:], False)[0])
        except Exception:  # noqa: BLE001
            parsed = None
    parsed = parsed or {}
    claims = verify([c for c in parsed.get("claims", []) if isinstance(c, dict)], calls)
    asked = numbers_in(question)
    for c in calls:
        for v in c["args"].values():
            asked += numbers_in(str(v)) if not isinstance(v, (int, float)) else [float(v)]
    answer, dropped = strip_unbacked(str(parsed.get("answer", final_text)), claims, [a for a in asked if a < 1e11])
    gap_rows = next((c["result"] for c in reversed(calls) if c["name"] == "gaps"), None)
    if gap_rows is None:
        gap_rows = run_tool("gaps", {"limit": 200})
    affected = gaps_affecting(claims, gap_rows)
    conf = parsed.get("confidence", "medium")
    if affected and conf == "high":
        conf = "medium"
    if not answer.strip():
        answer, conf = "I could not back a numeric answer with the recorded data for that question.", "low"
    result = {"question": question, "answer": answer, "claims": claims,
              "gaps_affecting_answer": affected, "model_notes": parsed.get("gaps_affecting_answer", []), "confidence": conf,
              "tool_calls": [{"id": c["id"], "tool": c["name"], "args": c["args"]} for c in calls[1:]],
              "dropped_unbacked_sentences": dropped, "model": b["model"], "seconds": round(time.time() - t0, 1)}
    _remember(question, result)
    return result
