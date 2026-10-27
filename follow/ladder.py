"""Pure metric arithmetic on a price ladder. Used for every venue so the numbers are comparable.

bids: [(price, size_base)] best (highest) first; asks: best (lowest) first.
Depth within N bps: USD notional of resting size at prices within N bps of mid, per side.
Slippage at size: (volume-weighted fill price - mid) / mid in bps for a market order of X USD, by walking the book.
A depth or slippage figure is None when the feed does not cover the price band / the book cannot fill the order.
"""

DEPTH_BPS = (5, 10, 25)
SLIP_USD = (10_000, 50_000, 100_000)


def walk(levels, notional_usd):
    """Average fill price for a notional-sized order, or None if the visible book is too small."""
    remaining = notional_usd
    cost = 0.0
    qty = 0.0
    for price, size in levels:
        lvl = price * size
        if lvl >= remaining:
            q = remaining / price
            cost += remaining
            qty += q
            return cost / qty
        cost += lvl
        qty += size
        remaining -= lvl
    return None


def ladder_metrics(bids, asks, bid_floor=None, ask_ceiling=None):
    """bid_floor / ask_ceiling: lowest bid / highest ask price the feed is known to cover
    (None means the whole book is known)."""
    out = {"two_sided": 0}
    if not bids or not asks:
        return out
    bb, ba = bids[0][0], asks[0][0]
    if bb >= ba:  # crossed local book: refuse to report
        return out
    mid = (bb + ba) / 2
    out.update(two_sided=1, best_bid=bb, best_ask=ba, mid=mid, spread_bps=(ba - bb) / mid * 1e4)
    for n in DEPTH_BPS:
        lo, hi = mid * (1 - n / 1e4), mid * (1 + n / 1e4)
        if bid_floor is None or bid_floor <= lo:
            out[f"bid_d{n}"] = sum(p * s for p, s in bids if p >= lo)
        if ask_ceiling is None or ask_ceiling >= hi:
            out[f"ask_d{n}"] = sum(p * s for p, s in asks if p <= hi)
    for x in SLIP_USD:
        k = f"{x // 1000}k"
        fb = walk(asks, x)
        fs = walk(bids, x)
        if fb is not None:
            out[f"buy_s{k}"] = (fb - mid) / mid * 1e4
        if fs is not None:
            out[f"sell_s{k}"] = (mid - fs) / mid * 1e4
    return out
