# FEEDBACK: Strike's L3 feed refreshes the whole book as 190 unbracketed events, once a second

*Written for the Strike team and the hackathon judges. Everything quoted here was measured on Strike mainnet by the Follow recorder
and can be reproduced with `python -m follow.analyze_churn` and `python -m follow.resample`. No Strike internals were used.*

---

## 1. TL;DR

Strike's public L3 feed is a good piece of engineering: sequence numbers never skipped in 58 snapshot replays, the book rebuilds exactly,
and every fill appears on the trade tape. But it has one design gap that undermines the thing Strike most wants from it, which is
**credible, analysable, deep liquidity**.

> The matching engine refreshes the whole BTC-USD book **once per second**, as a burst of about **190 separately sequenced events**
> (about 95 consecutive `cancel`s, then about 95 consecutive `open`s). The feed has **no batch boundary and no atomic replace**.
> Any consumer that reads the book while a burst is half-applied sees a half-empty book.

We measured the cost of that on ourselves: our first-generation scorecard read Strike's spread uptime as **86%**, its worst-case depth
as **$4.7k** and a $50k order as **4 to 8 bps**. Re-derived correctly from the same raw events, the figures are **99.99%**, **$315k** and
**0.67 bps**. Strike's book was far healthier than any naive consumer of its own public feed would conclude.

The fix is small and additive: a batch marker, an atomic `replace` action (the `modify` slot is already reserved), a bounded replay
endpoint and a periodic book checksum. Section 6 specifies it.

---

## 2. Context: what Strike is trying to achieve

Strike wants a deeper, more credible perps market: more takers trusting displayed liquidity, more market makers and RFQ Quoters
quoting, and ecosystem money (STRIKE incentives) spent where it improves depth. The public L3 feed exists to support that (its docs
list "liquidity and cancellation analytics" and "market-microstructure research" as use cases). Follow is exactly such a consumer.

---

## 3. The problem we hit

Building Follow's first scorecard, the Strike numbers looked bad and noisy. Spread uptime of 86% and a depth that sometimes collapsed
from about $340k to a few thousand dollars for a single sample did not match what the book looked like to the eye.

We had already verified the rebuilt book against Strike's REST snapshot, order for order (58 of 58 checkpoint replays match). So the
book was right and the *measurement* was wrong. Looking at the raw event stream explained why:

```
sequence  action  side
  n+0     cancel  buy      ┐
  n+1     cancel  buy      │  95 consecutive cancels  (the old quotes, both sides)
   ...     ...     ...     │
  n+94    cancel  sell     ┘      <-- the book is EMPTY here, in sequence order
  n+95    open    buy      ┐
  n+96    open    buy      │  95 consecutive opens    (the new quotes)
   ...     ...     ...     │
  n+189   open    sell     ┘      <-- the book is full again

  the whole burst spans ~1 ms of exchange time, then nothing for ~1 s, then it repeats
```

Nothing in the feed marks "these 190 events are one operation". A consumer sampling at a random instant, or serving a snapshot,
or computing depth after every message, lands inside a burst about 14% of the time.

---

## 4. Evidence

All numbers from live Strike mainnet data recorded by Follow (`python -m follow.analyze_churn`).

| Measurement | Result |
| --- | --- |
| Share of all L3 events that are `open` or `cancel` | **99.989%** (8.99M events; about 1,040 are fills, 1 `clear`) |
| New orders per fill, last 90 minutes | **~4,500 to 1** |
| Resting time of cancelled orders (n = 307,369) | p10 622 ms, **p50 993 ms**, p90 1,033 ms, p99 1,129 ms |
| Orders cancelled within 5 s of being placed | **100%** |
| Run lengths in the event stream (60 s) | median run **95**; longest cancel run **95**, longest open run **95** |
| Refresh bursts | median **190 events** over a median **1 ms** of exchange time, about one per second |
| Refresh bursts that leave the aggregated price-level book **identical** (905 bursts) | **32%** |
| Price levels that actually change in the other bursts (median) | **11** levels, from a burst of **190** events |
| Feed volume | about **14 million events per day** for a market with about 1,000 fills in 33 hours |
| `/ws/price` frames carrying several newline-separated JSON messages | **10 times** in our logs (not stated in the docs; see 8) |
| Handshake `503 Service Unavailable` on `/ws/price` and `/ws/l3` | **9** and **3** times in our logs |

**Effect on a naive consumer (the same raw events, two sampling methods)**

| Strike metric | Sampled at arbitrary instants (old) | Sampled between bursts (correct) |
| --- | --- | --- |
| Spread uptime (two-sided, <= 5 bps) | 86.3% | **99.99%** |
| Samples with spread > 5 bps | 13.1% | **0.01%** |
| Depth within 10 bps, 5th percentile | **$4,750** | **$315,092** |
| Depth within 10 bps, median | $341,116 | $345,157 |
| Slippage, $50k market order | ~4 to 8 bps | **0.67 bps** |

**Independent confirmation from Strike's own bookTicker feed.** The share of our samples whose best bid and ask match a `bookTicker` message
within 1.5 s was **68%** when we sampled at arbitrary instants and is **94% (16,356 of 17,417)** with burst-aware sampling. The remaining
6% is consistent with `bookTicker` being throttled to one message per 100 ms and with our once-per-second storage of it.

Two further observations follow from the same data. First, depth within 10 bps sits at **$349,0xx with almost no variance**: the same
ladder is re-posted every second. Second, only about 0.01% of events are trades. That is not a criticism of the quoting, it is a
statement about signal: **99.99% of what the feed carries is the refresh ritual, not market activity.**

---

## 5. The real pain point

The surface bug is "bursts are not bracketed". The real pain point is what that does to Strike's goal.

1. **Strike looks worse than it is, to everyone except Strike.** Any third party (a market maker's dashboard, a data vendor, a
   journalist, a judge) that computes depth or spread from L3 at arbitrary instants will publish a thinner, wider book than the matching
   engine actually shows. For an exchange trying to attract makers, that is a self-inflicted credibility problem. We nearly shipped it
   ourselves, and we were *trying* to be careful.
2. **Analysts cannot tell a requote from a pull.** A quote moved from price A to price B is represented as a `cancel` plus an unrelated
   `open` with a **new order ID** (documented), and `modify` is reserved but never emitted. So the feed cannot distinguish a maker
   *adjusting* a quote from a maker *withdrawing* liquidity. The cancel/fill ratio, the standard "quote quality" metric, becomes
   meaningless: ours reads about 4,500 : 1 and says nothing about maker behaviour. This is the information Strike's own incentive
   programme would need to reward committed liquidity.
3. **The recovery path is fragile and expensive.** There is no replay endpoint (documented). One missed message means a full snapshot,
   and snapshots are limited to 10 per second per IP. Every consumer also pays for about 14M events/day (roughly 3 GB/day of JSON by
   our estimate at about 230 bytes a message) to learn very little. Each of our 7 abnormal disconnects lost the events between the
   drop and the fresh snapshot; a replay window of even a few minutes would have healed all of them without a gap.
4. **Most of the stream carries no information.** Across 905 bursts, 32% left the price-level book exactly as it was, and in the rest a median of 11 of
   about 240 price levels moved. The feed pays for 190 events to communicate a handful of changes, because it has no way to say "renew", "amend" or
   "nothing changed". The one-second resting time (median 993 ms) is consistent with a time-in-force or refresh loop, but the feed gives consumers no
   field to tell.
5. **A one-second quote lifetime is itself a liquidity-quality fact** that deserves to be explicit. With p50 resting time of 993 ms,
   "displayed depth" is a property of the *refresh schedule*, not of committed capital, and a taker cannot tell the difference from L3.

What we cannot say, and do not claim: who is quoting (the IDs are opaque by design), whether the matching engine itself is atomic
(we only see the public feed), or whether the one-second cadence is intentional. We also do not claim Strike's book is manipulated;
the opposite is true, the book is deeper and tighter than the raw feed suggests.

---

## 6. What could have been done, and the near-perfect solution

### 6.1 Options considered

| Option | Verdict |
| --- | --- |
| Tell consumers to "wait for quiet" | what we had to do; heuristic, latency-dependent, breaks under load |
| Coalesce bursts into one L2 update server-side | loses the L3 value Strike is advertising |
| Add batch brackets (`batch_id`, `batch_end`) | tiny and additive; fixes the half-book problem completely |
| Atomic `replace` (use the reserved `modify` slot) | halves the feed and restores maker intent |
| Bounded replay endpoint | removes the full-resnapshot recovery path and the rate-limit pressure |
| Periodic book checksum | lets clients self-verify without polling REST |
| Document the wire format | zero cost, removes a class of consumer bugs |

### 6.2 The proposed design (backward compatible, opt-in)

Version the subscription, so existing clients see no change:

```json
{ "method": "SUBSCRIBE", "params": ["btc-usd@l3"], "version": 2, "id": 1 }
```

**(a) Batch brackets.** Add two fields to every `l3_update`:

```json
{ "type":"l3_update", "action":"cancel", "order_id":"...", "sequence":918275,
  "batch_id": 918270, "batch_end": false }
```

`batch_id` is the first sequence of the atomic group; the last event of the group carries `"batch_end": true`. A consumer applies events as
they arrive but only *publishes* its book at `batch_end`. A snapshot is always taken at a batch boundary.

**(b) Atomic replace.** Emit one event instead of a cancel plus an open, linking the old and new order:

```json
{ "type":"l3_update", "action":"replace", "replaces_order_id":"OLD", "order_id":"NEW",
  "side":"buy", "price":"81019.0", "delta_size":"0.04", "remaining_size":"0.30", "sequence":918301 }
```

Consequences: the burst shrinks from about 190 events to about 95, the feed halves (about 7M events/day), FIFO semantics are unchanged
(a replace keeps the cancel-plus-open priority rule), and analysts get the missing signal. `replace` events can be excluded from
"withdrawn liquidity" while true `cancel`s count, giving a meaningful cancel/fill ratio.

**(c) Replay.** `GET /v2/l3/events?symbol=BTC-USD&from_sequence=N&limit=5000`, served from a one-hour ring buffer the publisher already
has to keep to build snapshots. A consumer that missed a few messages fetches them instead of re-downloading the book.

**(d) Checksum.** Every second (at a batch boundary) publish:

```json
{ "type":"l3_checkpoint", "sequence":918340, "best_bid":"81019.0", "best_ask":"81020.0",
  "n_orders":190, "book_hash":"<64-bit hash of price,order_id,size in FIFO order>" }
```

Clients compare their local hash and resnapshot only on a mismatch.

**(e) Renew and net-change semantics.** Because most refreshes change nothing, add either a `renew` action (extends an order's life without a
cancel and a new ID) or a per-burst `batch_summary` (`levels_changed`, `net_depth_change_usd`) so a consumer can skip no-op bursts. Together with (b)
this removes most of the stream: our data says about 11 level changes per burst, against 190 events today.

**(f) Documentation.** State on `/ws/price` that a frame may contain several newline-separated messages (or send one per frame), and
return `Retry-After` on handshake `503`s.

### 6.3 Rollout plan

| Phase | Work | Risk | Done when |
| --- | --- | --- | --- |
| 0 | Fix docs (newline framing, burst behaviour, `503` handling) | none | docs published |
| 1 | Ship `batch_id` / `batch_end` behind `version: 2` | none for v1 clients | Follow's `analyze_churn` reports 100% of bursts bracketed |
| 2 | Replay endpoint backed by the existing sequence log | low | consumer can heal a 60 s gap without a snapshot |
| 3 | `replace` action; market-making bots migrate their requotes | medium (client migration) | opens-per-fill drops about 2x; cancel/fill becomes meaningful |
| 4 | Checksum messages; deprecate unbracketed v1 after a notice period | low | clients self-verify |

**Acceptance tests already exist.** `python -m follow.verify` (book equals REST snapshot) is the conformance test, and
`python -m follow.analyze_churn` measures the before and after: bursts bracketed, events per fill, resting-time distribution.

### 6.4 Expected impact (projections, not measurements)

| | Today | After phases 1 to 3 |
| --- | --- | --- |
| Third-party depth reading at an arbitrary instant | $4.7k to $349k (73x swing) | consistent, because books publish at `batch_end` |
| Feed volume | ~14M events/day | ~7M events/day |
| Cancel / fill as a quote-quality signal | uninformative (about 4,500 : 1) | meaningful (replace excluded) |
| Recovery from a short outage | full snapshot, rate limited | replay of the missing range |

---

## 7. What we shipped in Follow to cope (and its measured effect)

We cannot fix Strike's feed, so we fixed ourselves:

1. **Burst-aware sampling on Strike's own clock** (`follow/strike_l3.py`): the live recorder takes a sample just before any event that
   arrives at least 50 ms (in Strike's event timestamps) after the previous one, which is exactly the gap between two refresh bursts. Our first
   version waited for 50 ms of *arrival* silence instead; network jitter let about 5% of those samples land mid-burst again (spread over
   5 bps in 66 of 1,288 samples), so we switched to the exchange timestamps. After the switch: 0 of the live samples are mid-burst.
2. **History rebuilt from raw events** (`follow/resample.py`): replayed all 31 recorded sessions from their start snapshots with the same rule and
   re-derived **17,375** Strike samples, replacing the artifact-affected ones. The raw events were never modified.
3. **Disclosure**: the methodology page and the dataset notes now state this, with the before and after numbers above.
4. **Framing fix**: the market-data recorder now splits multi-message frames.

Measured effect on the Strike series: spread uptime 86.3% -> 100.0%, 5th-percentile depth $4,750 -> $315,092, $50k slippage 4 to 8 bps -> 0.68 bps.
Benchmarks are unaffected: Binance and Hyperliquid deliver whole-book snapshots or atomic diffs.

---

## 7a. Plan: effort, risks and how Strike would know it worked

| Item | Effort (estimate) | Owner |
| --- | --- | --- |
| Docs (newline framing, burst behaviour, `503` + `Retry-After`) | hours | docs |
| `batch_id` / `batch_end` on v2 subscriptions | 1 to 2 days (the publisher already assigns sequences in order) | feed publisher |
| Replay endpoint over a one-hour sequence log | 2 to 4 days (the log already exists to serve snapshots) | feed publisher |
| `replace` / `renew` actions and checkpoint hash | 1 to 2 weeks including market-maker migration | matching engine + MM integrations |

**Risks.** (1) Market-maker bots must adopt `replace`, so ship it additive and opt-in with v1 unchanged. (2) A replace must keep the cancel-plus-open
priority rule, or FIFO guarantees change. (3) Batch brackets must never span a trade, so a fill is not hidden inside a half-applied batch. (4) The
checksum must be defined over a canonical ordering, or clients will disagree.

**Acceptance criteria (all measurable with the scripts in this repo).**
1. 100% of events belong to a bracketed batch and a snapshot is always at a batch boundary (`analyze_churn`: bursts bracketed).
2. A consumer that publishes its book only at `batch_end` shows 0% half-empty samples (`resample` rule becomes unnecessary).
3. Events per fill falls by at least half and no-op bursts are skippable (`analyze_churn`: events per fill, state-neutral share).
4. A 60-second gap can be healed from replay without a snapshot, and the local book hash matches the published hash (`verify`).

**Open questions for Strike.** Is the one-second cadence a time-in-force or a market-maker loop? Is the engine itself atomic across a refresh? Would Strike
publish a net-change summary rather than the full burst?

## 7b. Summary

| | |
| --- | --- |
| **The problem** | The public L3 feed refreshes the whole book once a second as about 190 separately numbered, unbracketed cancel and open events. |
| **The real pain point** | Anyone reading the feed sees a thinner, wider book than Strike really has (86% against a true 99.99% spread uptime in our own scorecard), cancel/fill is meaningless, and 99.99% of the traffic is state-neutral refresh. That undermines credibility with the market makers and traders Strike wants. |
| **What could have been done** | Batch brackets, an atomic `replace`, a `renew` or net-change message, a replay endpoint and a book checksum. All additive. |
| **The fix we provide** | A specified, versioned, backward-compatible protocol (section 6), a rollout plan and acceptance tests; plus a working mitigation in Follow (exact-timestamp sampling and a history rebuilt from raw events). |
| **Proof it matters** | Reproducible with one command: `python -m follow.analyze_churn`. |

## 8. Smaller findings

- **Undocumented framing on `/ws/price`.** Frames sometimes carry two or more JSON messages separated by a newline. A parser that expects
  one message per frame raises `JSONDecodeError: Extra data` and drops the connection (it cost us 10 reconnects and the trades in between).
  The user-data stream docs mention batching; the market stream docs do not.
- **Intermittent handshake `503`s** on `/ws/price` (9) and `/ws/l3` (3), returned by the edge proxy as HTML with no `Retry-After`.
- **Clean abnormal closes** (`ConnectionClosedError(None, None, None)`, 7 on L3) with no close code, which makes "network" and "server
  restart" indistinguishable to a client. A close code on planned restarts would help.

## 9. What Strike got right

- **Sequence integrity**: zero holes across every recorded session, and one `clear` in 33 hours, which our recorder handled automatically.
- **Snapshot and stream agree exactly**: 58 of 58 checkpoint replays and a live 30 s check match order for order.
- **Trade tape consistency**: of the L3 fills recorded while our market feed was connected, **614 of 614 (100%)** appear on the public trade tape,
  and 614 of 616 tape trades have an L3 fill.
- **A public, unauthenticated L3 feed at all.** Almost no venue offers one. This project is only possible because Strike did.

## 10. Limits of this analysis

One symbol, about 33 hours of wall-clock time (11 hours actually recorded; the rest are marked gaps). The cause of the one-second refresh is
inferred from the public feed. The depth constancy is consistent with a single fixed-size ladder being re-posted, but we cannot attribute it.
The proposed field names are suggestions, not a spec Strike has reviewed.

## 11. Reproduce it

```bash
python -m follow.analyze_churn     # every number in section 4
python -m follow.resample          # rebuild Strike samples from raw events between refresh bursts
python -m follow.verify            # replay vs REST snapshots, trade tape cross-check
```
