# Follow dataset

Parquet (zstd), one file per table per UTC day: `<table>_<YYYY-MM-DD>.parquet`, plus `gaps.parquet`.
All timestamps are Unix epoch milliseconds. Decimal values from exchanges are kept as strings in raw tables.

## l3_events: every Strike L3 update, BTC-USD
| column | meaning |
| --- | --- |
| sequence | Strike per-symbol sequence; contiguous inside a session |
| session | recorder session; sequences restart their continuity at a new session after a gap |
| ts / recv_ts | exchange time / local receive time |
| action | open, cancel, partial_fill, full_fill, modify, clear |
| order_id, taker_order_id | opaque public ids |
| side | resting order side (buy or sell) |
| price, delta_size, remaining_size | decimal strings; delta is negative for reductions |
| trade_id | numeric trade id on fill events |

## book_samples: one row per venue every 2 seconds
`venue` is strike, binance or hyperliquid. `two_sided`=0 means an empty side or crossed book (other metric columns are null).
`bid_dN` / `ask_dN`: USD resting within N bps of mid (null when the venue feed does not cover the band).
`buy_sXk` / `sell_sXk`: slippage in bps of a $X market order (null when the visible book cannot fill it).
`seq` is the Strike L3 sequence or Binance update id. `exch_ts` is the exchange timestamp when available.

**Strike rows are burst-aware.** Strike's L3 feed refreshes the whole book once a second as a burst of about 190 events, so Strike samples are
taken between bursts (a gap of >= 50 ms in Strike's event timestamps). Rows before `meta.quiescent_sampling_since` were rebuilt from `l3_events` with the same rule
(`python -m follow.resample`); for those rows `ts` equals `exch_ts`. Benchmark venues are sampled live. See FEEDBACK.md.

## strike_trades / strike_ticker
Public trade tape and best bid/ask (at most one row per second) from `wss://api.strikefinance.org/ws/price`.

## gaps
`venue`, `start_ms`, `end_ms` (null while open), `reason`. During a gap the venue produced no samples and no events; do not interpolate across it. `scheduled_resync` gaps for Binance are the periodic book rebuilds (a few seconds).

## alerts
`ts`, `venue`, `kind` (stale or recovered), `message`, `delivered`. Written when a feed heartbeat goes stale and when it recovers.

## Use with care
History starts when the recorder started. Benchmarks are different instruments. See the methodology page.
