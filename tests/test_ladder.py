"""Pure arithmetic checks on the metric functions. Inputs are tiny worked examples; they never enter the product."""
import pytest

from follow.ladder import ladder_metrics, walk


def test_walk_exact_fill_at_one_level():
    assert walk([(100.0, 10.0)], 500.0) == pytest.approx(100.0)


def test_walk_across_levels():
    # $1000 at 100 (10 units) then $500 of the next level at 110
    avg = walk([(100.0, 10.0), (110.0, 10.0)], 1500.0)
    qty = 10 + 500 / 110
    assert avg == pytest.approx(1500 / qty)


def test_walk_unfillable_is_none():
    assert walk([(100.0, 1.0)], 1000.0) is None


def test_metrics_spread_depth_slippage():
    bids = [(99.99, 101.0), (99.0, 1000.0)]
    asks = [(100.01, 100.0), (101.0, 1000.0)]
    m = ladder_metrics(bids, asks)
    assert m["mid"] == pytest.approx(100.0)
    assert m["spread_bps"] == pytest.approx(2.0)
    # 5 bps of mid = 0.05: only the touch level is inside
    assert m["bid_d5"] == pytest.approx(99.99 * 101)
    assert m["ask_d5"] == pytest.approx(100.01 * 100)
    # $10k fits inside the touch level ($10,001) -> slippage = half spread = 1 bp
    assert m["buy_s10k"] == pytest.approx(1.0, abs=1e-6)
    assert m["sell_s10k"] == pytest.approx(1.0, abs=1e-6)
    # $100k exceeds the visible book on each side (about $10k + $1M) -> fillable, with extra cost
    assert m["buy_s100k"] > 1.0


def test_one_sided_and_crossed_books_report_nothing():
    assert ladder_metrics([], [(1.0, 1.0)]) == {"two_sided": 0}
    assert ladder_metrics([(2.0, 1.0)], [(1.0, 1.0)]) == {"two_sided": 0}


def test_coverage_limits_hide_uncovered_bands():
    bids = [(99.99, 100.0), (99.98, 100.0)]
    asks = [(100.01, 100.0), (100.02, 100.0)]
    m = ladder_metrics(bids, asks, bid_floor=99.98, ask_ceiling=100.02)
    assert "bid_d5" not in m and "ask_d25" not in m  # feed does not reach 5 bps from mid
