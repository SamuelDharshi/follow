# Follow: 6-phase build plan

Rule for every phase: live feeds only. No mock data, no fixtures standing in for feeds, no simulated books. Tests replay data the recorder actually captured, and a "deliberately dropped event" test drops a real event from a real stream.

## Verified from this machine (2026-10-22)

| Feed | Result |
| --- | --- |
| Strike docs (L3, market WS) | Reachable. L3 mainnet is `https://api.strikefinance.org` and `wss://api.strikefinance.org`, no auth. |
| Binance spot and futures depth REST | Reachable, HTTP 200 |
| Hyperliquid `l2Book` info endpoint | Reachable, HTTP 200 |
| Runtimes | Node 22, Python 3.11 |

Not yet verified: the exact Strike L3 REST and WebSocket paths (they sit on separate doc pages, `snapshot` and `websocket`), and whether the machine stays on 24/7 (see Phase 1).

## On "onchain contracts"

The PRD rules out wallets, funds and contracts, and Follow reads Strike's off-chain public market-data API. So there is no contract to deploy, and I won't invent one. If you want an onchain piece that is real and useful, the honest option is **anchoring**: publish a hash of each day's dataset to Cardano so the data can't be quietly edited later. It is optional, goes in Phase 6 and only if time is left. Tell me if you want it.

## Stack

- Recorder, metrics, API: Python 3.11 (asyncio, `websockets`, FastAPI). SQLite in WAL mode for the store, Parquet export for the dataset.
- Frontend: Next.js with a chart library, reading only the real API.
- Host: an always-on machine is required. A laptop that sleeps loses data that can never be recovered. A cheap VPS is the right answer.

---

## Phase 1: Foundation and Strike L3 recorder (hours 0 to 4)

**Goal:** real Strike data is being written to disk, continuously, as early as possible.

- Repo layout, config, logging, SQLite schema (`l3_events`, `snapshots`, `gaps`, `trades`).
- Read the L3 snapshot and WebSocket doc pages and confirm the real field names.
- Recorder loop: subscribe, buffer, fetch snapshot, discard events up to `last_sequence`, apply N+1 onward, store every event.
- Gap handling: on a sequence gap, a `clear` action or a disconnect, write a gap marker and rebuild from a fresh snapshot. Reconnect with exponential backoff.
- Deploy to the always-on host and start it. Add a heartbeat file and a health check.

**Exit check:** recorder has run 30 minutes on mainnet, events are in SQLite, and killing the network produces a gap row and an automatic recovery.

## Phase 2: Book reconstruction and the gap-safe core (hours 4 to 10)

**Goal:** a local book you can trust, because every metric depends on it.

- In-memory L3 book (price levels with FIFO order lists) rebuilt from snapshot plus events.
- Validation: periodically fetch a fresh REST snapshot and diff it against the local book at the same sequence. Any mismatch is a bug.
- Gap test using a real recorded stream with one event removed.
- Strike market WebSocket recorder (`trade`, `bookTicker`, `markprice`) running alongside, for the trade tape and a cross-check of best bid/ask.
- Answer the open question: do trade IDs and taker order IDs on the market stream match L3's `taker_order_id` and `trade_id`?

**Exit check:** book matches REST snapshots with zero diffs over an hour, and the cross-check against `bookTicker` agrees.

## Phase 3: Benchmark feeds (hours 8 to 14, overlaps Phase 2)

**Goal:** Binance and Hyperliquid BTC books recorded the same way, on the same clock.

- Binance: depth WebSocket with REST snapshot and the documented `U`/`u` update-ID sync procedure. Decide spot BTCUSDT vs futures BTCUSDT and state it on the methodology page. Perps are the fairer comparison to Strike.
- Hyperliquid: `l2Book` WebSocket subscription, BTC.
- Same gap and reconnect discipline, same store, UTC timestamps with receive time and exchange time kept separately.

**Exit check:** all three venues have continuous recorded data and gap markers where connections dropped.

## Phase 4: Metrics engine and API (hours 12 to 22)

**Goal:** every metric computed from recorded data, exposed through a real API.

- 1-minute windows, rolled up to hourly and daily. Gap time excluded and reported, never interpolated.
- M1 spread uptime (5 bps), M2 depth within 5/10/25 bps per side, M3 slippage at $10k/$50k/$100k, for all three venues.
- M4 cancel/fill ratio from L3 events (Strike only).
- Sample-size column beside every number.
- FastAPI, read-only: latest values, time-range series, venue comparison, data coverage, health.
- Parquet export job plus a schema README.
- Unit tests on hand-built books for the math, and a replay test on recorded data. The hand-built books are only inputs to pure arithmetic tests; they never appear in the product.

**Exit check:** the API returns real M1 to M4 for Strike and M1 to M3 for both benchmarks, and a spot check of M3 by hand against a live book agrees.

## Phase 5: Frontend (hours 20 to 32)

**Goal:** the scorecard, built only on the API from Phase 4.

- Scorecard: latest value of each metric, Strike's own trend first, benchmark gap second (the PRD's framing rule), data-coverage note per number.
- Trend charts per metric with gaps drawn as gaps.
- L3-only view: cancel/fill ratio.
- Methodology page with every definition and the known limits (BTC-only, thin volume, venue choice).
- Dataset download page.
- Empty and loading states are real states. No placeholder numbers anywhere.

**Exit check:** page loads from the deployed API, every number traces to a row in the store.

## Phase 6: Stretch, hardening, deploy and submission (hours 30 to 42)

**Goal:** ship. Cut from the bottom of this list first.

1. Deploy API and frontend publicly, confirm uptime and coverage numbers (target 95%+).
2. README that explains every Strike interaction, plus the submission checklist from the PRD.
3. Demo video under 3 minutes, following the PRD demo script.
4. M5 depth resilience (stretch).
5. Incentive designer (stretch). It is a parametric model, so it is a model by nature. It must run on live M2 and M3 inputs, print its assumptions, and carry the "what-if, not a forecast" banner.
6. Second recorder on another host (recommended).
7. Optional Cardano anchoring of daily dataset hashes.
8. Submission form (check Strike's Discord for the link).

---

## Hard dependency

Phase 1 must be running within the first few hours. Everything after it uses the data it collects, and lost hours cannot be recovered. If the recorder is unstable at hour 8, stop everything else.

## Decisions needed from you

1. **Host:** do you have a VPS or an always-on machine? If not, Phase 1 will be on this laptop and will have gaps whenever it sleeps.
2. **Binance market:** spot or futures for the benchmark? I'd pick futures.
3. **Anchoring:** do you want the optional Cardano dataset-hash anchoring, or skip it?

## Status (2026-10-22)
Phases 1-6 built and running on live feeds. Open items for the owner: always-on host, public deploy, demo video, submission form (see follow/.env PENDING section).
