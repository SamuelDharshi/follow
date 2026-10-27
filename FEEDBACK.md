# FEEDBACK: agents need capability discovery that tells the truth

*Written for the Open Agent Hackathon 2026 judges and the NVIDIA, Zetaris and Meterless teams. Everything quoted was measured while building Follow; [scripts/probe_sponsors.py](scripts/probe_sponsors.py) reproduces the numbers (needs your own `NVIDIA_API_KEY` and a local Zetaris platform).*

## 1. Summary

Follow is an agent that answers questions with checked evidence. To build it we had to use NVIDIA's hosted Nemotron models, Zetaris's SQL API and Meterless's H-MEM spec. All three work. The same problem showed up in each, and it cost us more time than any actual feature:

> **An agent cannot ask the platform what it can do. It has to call and see what breaks, and the failure is either a wrong status, a silent empty result, or a value of the wrong type.**

| Sponsor | What advertises a capability | What actually happens | Measured |
|---|---|---|---|
| NVIDIA | `GET /v1/models` lists the model | Calling it returns `404 Function '…': Not found for account` | **6 of 11** listed Nemotron chat models fail with our key |
| NVIDIA | Reasoning is on by default | The thinking budget is spent before the answer; `content` can be empty with `finish_reason: "stop"` | **2 of 5** runs empty at `max_tokens=300`; 3.8 s median vs 1.0 s with thinking off |
| Zetaris | One SQL endpoint, `select` field | DDL, `SHOW`, anything but `SELECT` → `400 Bad Select SQL`; numbers come back as strings | `{"one":"1","dbl":"2.5"}` for `SELECT 1, 2.5` |
| Zetaris | `X-Org-ID` header | Organisation *name* rejected, only the numeric id works | `400 Invalid value for: header X-Org-ID` |
| Meterless | H-MEM spec | Spec only; no hosted store to call, reference engine is TypeScript | We had to re-implement a subset in Python |

We picked **one** problem to propose a fix for, because the others are symptoms of it: **a machine-readable, honest capability contract** (section 5).

## 2. The problem

An agent loop is: choose a tool, call it, read the result, decide. Every step assumes the tool surface is *discoverable and typed*. In practice:

1. **Discovery lies (NVIDIA).** `/v1/models` returned 85 models. Eleven are Nemotron chat models. We called each once with `max_tokens=8`:

   ```
   200  nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
   200  nvidia/nemotron-3-ultra-550b-a55b
   200  nvidia/nemotron-3.5-bolt-e4b
   200  nvidia/nemotron-3.5-lightning-30b-a3b
   200  nvidia/nemotron-3.5-super-vl-120b-a12b
   404  nvidia/llama-3.1-nemotron-51b-instruct       Function '5beba52c-…': Not found for account
   404  nvidia/llama-3.1-nemotron-70b-instruct       …
   404  nvidia/llama-3.1-nemotron-ultra-253b-v1      …
   404  nvidia/nemotron-3-super-120b-a12b            …
   404  nvidia/nemotron-4-340b-instruct              …
   404  nvidia/nemotron-nano-3-30b-a3b               …
   ```

   Earlier in the build the model we first chose (`llama-3.3-nemotron-super-49b-v1`) returned `410` end-of-life. A 404 reading "Function '<uuid>' not found" tells a developer nothing: is the name wrong, is the model retired, or is it not enabled for my account? Those need three different fixes.

2. **Defaults hide cost and failure (NVIDIA).** Same prompt (`Reply with ONLY this JSON …`), `nemotron-3.5-lightning-30b-a3b`, `max_tokens=300`, five runs each:

   | | median latency | empty `content` | completion tokens |
   |---|---|---|---|
   | default | 3.8 s | **2 / 5** | 288, 256, 300, 300, 224 |
   | `chat_template_kwargs: {"enable_thinking": false}` | 1.0 s | 0 / 5 | 10, 10, 10, 10, 10 |

   The answer is ten tokens; the default spends up to 30x that thinking, and when the budget runs out the reply is an empty string that still says `finish_reason: "stop"`. An agent that parses JSON from `content` fails on a response the API calls successful. The switch that fixes it is a non-standard field (`chat_template_kwargs`) that we found by trial.

3. **The SQL surface is narrower than it looks (Zetaris).**

   ```
   POST /api/v1.0/query/sql/start {"select": "CREATE LIGHTNING DATABASE …"} -> 400 Bad Select SQL at 'select'
   POST /api/v1.0/query/sql/start {"select": "SHOW TABLES"}                  -> 400 Bad Select SQL at 'select'
   POST /api/v1.0/query/sql/start {"select": "SELECT 1 AS one, 'a' AS letter, CAST(2.5 AS DOUBLE) AS dbl"}
        -> 200 {"records":[{"one":"1","letter":"a","dbl":"2.5"}], …}   (all values are JSON strings)
   ```

   Creating the table that the agent queries required a second protocol (the JDBC driver, a JVM and a 100 MB jar). The result schema is not returned, so a client cannot tell `"1"` the string from `1` the integer; we had to coerce on our side, and the claim verifier would otherwise reject every Zetaris number. The field is called `select` but the error message is the only place that says why DDL fails. The organisation id behaves the same way: the UI shows the organisation *name* and the login header needs the numeric id (`400 Invalid value for: header X-Org-ID` for the name, `200` for `1`).

   Smaller: the public API docs at `/redoc/index.html` are a 640-byte shell that loads `/redoc/docs.yaml` with JavaScript, so a text crawler or an agent reading the docs sees nothing (`/openapi.json`, `/swagger.json`, `/llms.txt` are all 404). The local-file-store option is documented for S3 only; we found `FORMAT PARQUET OPTIONS (PATH …)` by trial.

4. **No callable memory (Meterless).** H-MEM defines tiers, weights, provenance and supersession well, but it is a specification plus a TypeScript reference. There is no endpoint to point an agent at, so every agent author re-implements the rules and nobody can check that two implementations agree. Our Python subset (`follow/hmem.py`) follows the weights and thresholds but has **not** been run against a conformance suite, because none exists that we could find.

## 3. The real pain point

It is not that any one call fails. It is that **the failure arrives late and sideways**:

- a listing says yes, the call says 404;
- a call says success, the field is empty;
- a SQL call says 200, the numbers are strings;
- a spec says "implement me", there is nothing to test against.

For a human these are ten-minute annoyances. For an agent whose job is to *tell the truth about its evidence* they are the product risk: Follow's honesty layer exists specifically to catch an answer that is not backed by a tool result. A silently empty or mistyped tool result forces it to either drop a correct claim or, worse, pass a wrong one.

Our measured cost of the pain: three model-selection restarts, two rewrites of the response parser, one coercion layer, and a JDBC detour for a one-time `CREATE TABLE`.

## 4. What could have been done

| Fix | Effort | Who |
|---|---|---|
| `/v1/models` returns only models the key can call, plus `deprecated`, `retires_on`, `requires_enablement` | small | NVIDIA |
| Distinguish `model_not_found` / `model_retired` / `not_enabled_for_account` in the error body | small | NVIDIA |
| Empty `content` with spent reasoning budget returns `finish_reason: "length"` and a `reasoning_tokens` count | small | NVIDIA |
| Document `enable_thinking` on the model card, make the per-request switch a first-class `reasoning: {enabled}` field | small | NVIDIA |
| Return a `schema` array (`name`, `type`) with every SQL page and typed JSON values | medium | Zetaris |
| Say in the endpoint description that only `SELECT` is accepted; offer `/query/sql/execute` for DDL behind a permission | medium | Zetaris |
| Accept the organisation name or id; render the OpenAPI spec as static HTML | small | Zetaris |
| Publish a hosted H-MEM endpoint or, at minimum, a language-neutral JSON conformance suite | medium | Meterless |

## 5. Near-perfect solution: a capability contract (`/.well-known/agent-capabilities.json`)

One small, versioned, machine-readable document per platform that an agent fetches **before** it plans. It lists what *this credential* can do right now and the shape of what comes back.

```jsonc
{
  "contract": "agent-capabilities/1",
  "credential": {"scope": "account", "checked_at": "2026-10-28T09:00:00Z"},
  "models": [
    {"id": "nvidia/nemotron-3.5-lightning-30b-a3b", "callable": true,
     "reasoning": {"default": "on", "switch": "reasoning.enabled", "typical_overhead_tokens": 250},
     "tool_calls": true, "json_mode": true, "retires_on": null},
    {"id": "nvidia/nemotron-4-340b-instruct", "callable": false, "reason": "not_enabled_for_account"}
  ],
  "sql": {"statements": ["SELECT"], "ddl_via": "jdbc", "result_types": "typed"},
  "memory": {"tiers": ["short_term", "working", "long_term"], "conformance": "https://…/h-mem/tests.json"}
}
```

Why this and not three separate patches:

- **One fetch replaces trial and error.** The agent (or its operator) learns at start-up that a model is unavailable, instead of at call 4 of a user's question.
- **It is testable.** A CI check can assert `callable == true` for every model a product depends on, so a retirement (our `410`) is a failed build, not a failed demo.
- **It makes honesty cheaper.** Typed results mean the verifier compares numbers, not strings.

## 6. Plan

What we did in this repository (done) versus what the sponsors would have to do (proposal only):

| Step | Status |
|---|---|
| Probe script that records the discovery/call mismatch and thinking cost | **Done**: [scripts/probe_sponsors.py](scripts/probe_sponsors.py) |
| Workarounds in Follow: thinking off for NVIDIA, string-to-number coercion for Zetaris, org id config, JDBC bootstrap for DDL | **Done**: `follow/agent.py`, `follow/zetaris.py` |
| Client-side "capability check" at start-up: call each configured model once and fail fast | **Next**: ~1 day; small, uses the probe code |
| Contract schema (JSON Schema) and a reference generator for Follow's own API (`/.well-known/agent-capabilities.json`) | **Next**: ~2 days; would be the first working example |
| Sponsor-side changes in section 4 | **Proposal**: we cannot make these |

## 7. Evidence, limits and honesty

- All numbers are from one account on one day (2026-10-28). The model list and entitlements will differ for other accounts; the *mismatch* is the point, not the exact six.
- Thinking-mode figures are five runs per setting on a tiny prompt. Direction is clear (empty replies, 4x latency); the exact rates are not a benchmark.
- Zetaris was tested on the **local Docker platform** (bundle 2.4.3.1), not the cloud SaaS. The cloud docs were read, not exercised, apart from the public spec URLs listed above.
- We did not test SpaceX AI at all; nothing in this document concerns it.
- Meterless: we read the spec and implemented a subset. We make no claim about the TypeScript engine's behaviour because we did not run it.
- Where we say "we found by trial" we mean the documentation we read did not state it; it may be documented somewhere we did not look.

## 8. What went well

- Nemotron 3.5 Lightning with thinking off is fast (about 1 s) and follows JSON-only instructions reliably. It is why the agent loop is usable at all.
- The Zetaris platform ran locally from one Docker bundle and queried a 104,664-row Parquet file through plain SQL once the table existed.
- H-MEM's required `source`, `confidence` and `provenance` fields map directly onto what an honest agent should remember, and made the memory design easy to reason about.
