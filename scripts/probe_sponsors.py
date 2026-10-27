"""Reproduces the sponsor-technology findings written up in FEEDBACK.md. Needs NVIDIA_API_KEY and a running local Zetaris platform (see .env).

Run: python scripts/probe_sponsors.py        (prints results; no secret is printed)
"""
import json
import os
import statistics
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
NV = "https://integrate.api.nvidia.com/v1"
Z = os.environ.get("ZETARIS_BASE_URL", "http://localhost:8888")


def nvidia() -> None:
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        print("NVIDIA_API_KEY not set; skipping")
        return
    h = {"Authorization": f"Bearer {key}"}
    print("== NVIDIA ==")
    ids = [m["id"] for m in httpx.get(NV + "/models", headers=h, timeout=30).json()["data"]]
    chat = [i for i in ids if "nemotron" in i.lower() and not any(x in i.lower() for x in ("embed", "safety", "parse", "reward", "guard"))]
    print(f"/v1/models lists {len(ids)} models, {len(chat)} are Nemotron chat models. Calling each once (max_tokens=8):")
    bad = 0
    for m in chat:
        t = time.time()
        r = httpx.post(NV + "/chat/completions", headers=h, timeout=60,
                       json={"model": m, "messages": [{"role": "user", "content": "Say ok"}], "max_tokens": 8})
        ok = r.status_code == 200
        bad += not ok
        why = "" if ok else " " + (r.json().get("detail") or r.text)[:70].replace("\n", " ") if r.headers.get("content-type", "").startswith("application/") else ""
        print(f"  {r.status_code} {time.time() - t:4.1f}s {m}{why}")
    print(f"  -> {bad} of {len(chat)} models listed by /v1/models cannot be called with this key")

    m = "nvidia/nemotron-3.5-lightning-30b-a3b"
    body = {"model": m, "messages": [{"role": "user", "content": 'Reply with ONLY this JSON: {"answer":"hi","n":1}'}], "max_tokens": 300, "temperature": 0.1}
    print(f"\nThinking mode on the same prompt ({m}), 5 runs each, max_tokens=300:")
    for label, extra in (("default (thinking on)", {}), ("enable_thinking=false", {"chat_template_kwargs": {"enable_thinking": False}})):
        times, empties, toks = [], 0, []
        for _ in range(5):
            t = time.time()
            j = httpx.post(NV + "/chat/completions", headers=h, timeout=90, json={**body, **extra}).json()
            times.append(time.time() - t)
            msg = j["choices"][0]["message"]
            empties += not (msg.get("content") or "").strip()
            toks.append(j.get("usage", {}).get("completion_tokens"))
        print(f"  {label:24} median {statistics.median(times):4.1f}s | empty `content`: {empties}/5 | completion tokens: {toks} | finish: {j['choices'][0]['finish_reason']}")


def zetaris() -> None:
    org_name, org_id = "zetaris", os.environ.get("ZETARIS_ORG_ID", "1")
    user, pw = os.environ.get("ZETARIS_USERNAME"), os.environ.get("ZETARIS_PASSWORD")
    print("\n== Zetaris (local platform) ==")
    if not (user and pw):
        print("ZETARIS_USERNAME/PASSWORD not set; skipping")
        return
    rid = lambda: {"X-Request-ID": str(uuid.uuid4())}  # noqa: E731
    r = httpx.get(Z + "/api/v1.0/auth/login", headers={**rid(), "X-Org-ID": org_name}, auth=(user, pw), timeout=20)
    print(f"login with the organisation NAME in X-Org-ID  -> {r.status_code} {r.text[:80]!r}")
    r = httpx.get(Z + "/api/v1.0/auth/login", headers={**rid(), "X-Org-ID": org_id}, auth=(user, pw), timeout=20)
    print(f"login with the numeric id {org_id!r}              -> {r.status_code}")
    tok = r.json()["idToken"]
    h = lambda: {**rid(), "X-Org-ID": org_id, "Authorization": f"Bearer {tok}"}  # noqa: E731
    for sql in ("CREATE LIGHTNING DATABASE probe DESCRIBE BY \"x\"", "SHOW TABLES", "SELECT 1 AS one, 'a' AS letter, CAST(2.5 AS DOUBLE) AS dbl"):
        q = httpx.post(Z + "/api/v1.0/query/sql/start", headers=h(), json={"select": sql, "pageLimit": 5}, timeout=60)
        shown = q.text[:130].replace("\n", " ")
        print(f"REST sql/start {sql[:38]!r:42} -> {q.status_code} {shown}")
        if q.status_code == 200:
            token = q.json()["queryToken"]
            print("   value types returned:", {k: type(v).__name__ for k, v in q.json()["records"][0].items()}, "| keys in response:", sorted(q.json()))
            httpx.delete(Z + f"/api/v1.0/query/sql/close/{token}", headers=h(), timeout=20)
    for path in ("/openapi.json", "/v3/api-docs", "/swagger.json", "/llms.txt"):
        c = httpx.get("https://api.saas.enterprise.zetaris.com" + path, timeout=20)
        print(f"public spec probe {path:16} -> {c.status_code}")
    c = httpx.get("https://api.saas.enterprise.zetaris.com/redoc/index.html", timeout=20)
    print(f"redoc page: {c.status_code}, {len(c.text)} bytes of HTML; contains spec-url={'spec-url' in c.text or 'docs.yaml' in c.text}; real spec at /redoc/docs.yaml -> "
          f"{httpx.get('https://api.saas.enterprise.zetaris.com/redoc/docs.yaml', timeout=20).status_code}")


if __name__ == "__main__":
    nvidia()
    zetaris()
    sys.exit(0)
