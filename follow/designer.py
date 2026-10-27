"""Incentive designer: a parametric what-if model on the REAL current Strike book. Not a forecast.

Model (every assumption is returned with the result and printed beside it in the UI):
  participation = clamp(rebate_bps / adverse_selection_bps, 0, 1)
  added liquidity per side (USD) = n_quoters * quote_size_usd * participation
  The added size is placed at the current best bid and best ask (joining the touch), then M2 and M3 are
  recomputed on the resulting ladder with the same functions used for the live scorecard.
Nothing here predicts how makers or traders will actually behave.
"""
import json

from . import db
from .ladder import DEPTH_BPS, ladder_metrics

MAX_BOOK_AGE_MS = 120_000


def run(con, rebate_bps: float, n_quoters: int, quote_size_usd: float, adverse_selection_bps: float = 1.5,
        turnover_per_day: float = 1.0) -> dict:
    raw = db.get_meta(con, "strike_latest_book")
    if not raw:
        raise ValueError("no Strike book recorded yet")
    book = json.loads(raw)
    age = db.now_ms() - book["ts"]
    from . import config
    if age > MAX_BOOK_AGE_MS and not config.SNAPSHOT_MODE:
        raise ValueError(f"latest recorded Strike book is {age // 1000}s old; recorder may be down")
    bids, asks = [tuple(x) for x in book["bids"]], [tuple(x) for x in book["asks"]]
    before = ladder_metrics(bids, asks)
    if not before["two_sided"]:
        raise ValueError("the current Strike book is one-sided; nothing to model against")
    participation = max(0.0, min(1.0, rebate_bps / adverse_selection_bps)) if adverse_selection_bps > 0 else 1.0
    add_usd = n_quoters * quote_size_usd * participation
    nb = list(bids)
    na = list(asks)
    if add_usd > 0:
        nb[0] = (bids[0][0], bids[0][1] + add_usd / bids[0][0])
        na[0] = (asks[0][0], asks[0][1] + add_usd / asks[0][0])
    after = ladder_metrics(nb, na)
    keys = [f"{s}_d{n}" for n in DEPTH_BPS for s in ("bid", "ask")] + \
           [f"{s}_s{k}" for k in ("10k", "50k", "100k") for s in ("buy", "sell")]
    # cost to the programme: rebate paid on the modelled maker volume
    maker_volume_usd = 2 * add_usd * turnover_per_day
    return {
        "book_ts": book["ts"], "book_seq": book["seq"], "book_age_ms": age,
        "baseline": {k: before.get(k) for k in keys + ["spread_bps", "mid"]},
        "modelled": {k: after.get(k) for k in keys + ["spread_bps", "mid"]},
        "participation": participation, "added_liquidity_usd_per_side": add_usd,
        "programme_cost_usd_per_day": maker_volume_usd * rebate_bps / 1e4,
        "assumptions": [
            "This is a what-if model, not a forecast.",
            f"Each Quoter participates in proportion to rebate / adverse-selection cost: participation = min(1, {rebate_bps} bps / {adverse_selection_bps} bps) = {participation:.2f}.",
            f"Added size is {n_quoters} x ${quote_size_usd:,.0f} x participation per side, placed at the current best bid and best ask.",
            "The baseline is Strike's real most-recently recorded L3 book; metrics reuse the live scorecard functions.",
            f"Programme cost assumes maker volume = 2 sides x added size x {turnover_per_day} turnover/day, paid the rebate.",
            "Existing resting orders, taker flow and Quoter behaviour are held fixed. Real participation, quote placement and adverse selection may differ materially.",
        ],
    }
