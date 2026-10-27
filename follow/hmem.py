"""Agent memory shaped after the open H-MEM spec (github.com/Meterless/Meterless/tree/main/engines/hmem).

What follows the spec: tiered records (short_term / working / long_term) with required `source`, `confidence` and `provenance`; `supersedes` /
`supersededBy` links; hybrid retrieval ranked by keyword, tag, domain, layer weight (0.6 / 0.8 / 1.0), recency and a superseded penalty, multiplied by
confidence and cut at a threshold (default 0.35).
What it is not: the spec's reference engine is TypeScript and this Python store has NOT been run through its conformance suite. No embeddings, no decay
service, no dreaming or sleep cycle. It is a small honest subset, stored as JSON next to the database.
"""
import json
import os
import re
import time
import uuid

from . import config

PATH = os.path.join(os.path.dirname(config.DB_PATH) or ".", "agent_memory.json")
LAYER_W = {"short_term": 0.6, "working": 0.8, "long_term": 1.0}
THRESHOLD = 0.35
_STOP = set("the a an of to in on is are was were be by for and or how why what did does do it its at as with from that this than then".split())


def _load() -> list[dict]:
    try:
        return json.load(open(PATH, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(PATH) or ".", exist_ok=True)
    json.dump(rows[-300:], open(PATH, "w", encoding="utf-8"))


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in _STOP}


def _key(content: str) -> str:
    return re.sub(r"[\d.,$%]+", "#", content.lower())[:90]


def add(content: str, *, source: str, confidence: float, provenance: dict, type: str = "factual", layer: str = "working",
        tags: list[str] | None = None, domain: str = "liquidity", namespace: str = "follow") -> dict:
    """Records without `source` or `provenance` are rejected, as the spec requires."""
    if not source or not provenance:
        raise ValueError("H-MEM: source and provenance are mandatory")
    rows = _load()
    rec = {"id": uuid.uuid4().hex[:12], "content": content, "type": type, "layer": layer, "timestamp": int(time.time() * 1000), "lastAccessed": None,
           "accessCount": 0, "tags": tags or [], "domain": domain, "namespace": namespace, "confidence": confidence, "source": source,
           "provenance": provenance, "supersedes": None, "supersededBy": None}
    for old in rows:  # a newer finding about the same thing supersedes the older one (same tags and same wording once numbers are masked)
        if not old["supersededBy"] and old["tags"] == rec["tags"] and _key(old["content"]) == _key(content):
            old["supersededBy"], rec["supersedes"] = rec["id"], old["id"]
    rows.append(rec)
    _save(rows)
    return rec


def recall(query: str, k: int = 4, tags: list[str] | None = None) -> list[dict]:
    q = _words(query)
    now = time.time() * 1000
    rows, scored = _load(), []
    for r in rows:
        kw = len(q & _words(r["content"] + " " + " ".join(r["tags"]))) / max(len(q), 1)
        tg = 1.0 if tags and set(tags) & set(r["tags"]) else 0.0
        age_h = (now - r["timestamp"]) / 3.6e6
        rec = 1.0 / (1.0 + age_h / 24)
        s = (0.55 * kw + 0.15 * tg + 0.10 * (r["domain"] == "liquidity") + 0.20 * rec) * LAYER_W.get(r["layer"], 0.8) * r["confidence"]
        if r["supersededBy"]:
            s *= 0.3
        if s >= THRESHOLD or (kw > 0 and s >= THRESHOLD * 0.7):
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, r in scored[:k]:
        r["lastAccessed"], r["accessCount"] = int(now), r["accessCount"] + 1
        out.append({**r, "score": round(s, 3)})
    if out:
        _save(rows)
    return out
