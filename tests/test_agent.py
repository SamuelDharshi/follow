"""Tests for the agent's honesty enforcement. Tool results are REAL (read from the recorded database); the 'model output' strings are
hand-written inputs that exercise the checker, exactly as the arithmetic tests use hand-built books."""
import os

import pytest

from follow import agent, config

pytestmark = pytest.mark.skipif(not os.path.exists(config.DB_PATH), reason="no recorded data")


@pytest.fixture(scope="module")
def real():
    sc = agent.run_tool("scorecard", {"window_minutes": 60, "compare": "prev"})
    return [{"id": "c1", "name": "scorecard", "args": {"window_minutes": 60}, "result": sc}], sc


def test_claim_matching_a_tool_number_is_kept(real):
    calls, sc = real
    uptime = sc["venues"]["strike"]["current"]["m1_spread_uptime"]
    kept = agent.verify([{"text": "Strike spread uptime", "tool": "scorecard", "args": {}, "value": uptime}], calls)
    assert len(kept) == 1 and kept[0]["call_id"] == "c1"


def test_percent_form_of_a_fraction_is_accepted(real):
    calls, sc = real
    uptime = sc["venues"]["strike"]["current"]["m1_spread_uptime"]
    kept = agent.verify([{"text": f"Strike spread uptime was {uptime * 100:.1f}%", "tool": "scorecard", "args": {}, "value": round(uptime * 100, 1)}], calls)
    assert len(kept) == 1


def test_invented_number_is_dropped(real):
    calls, _ = real
    kept = agent.verify([{"text": "Strike depth was 987654321", "tool": "scorecard", "args": {}, "value": 987654321}], calls)
    assert kept == []


def test_claim_citing_a_tool_that_was_never_called_is_dropped(real):
    calls, sc = real
    v = sc["venues"]["strike"]["current"]["m1_spread_uptime"]
    assert agent.verify([{"text": "x", "tool": "toxicity", "args": {}, "value": v}], calls) == []


def test_sentences_with_unbacked_numbers_are_removed():
    claims = [{"text": "Strike slippage", "tool": "scorecard", "value": 0.62}]
    out, dropped = agent.strip_unbacked("A $50k order costs 0.62 bps on Strike. Binance is 17.3 bps worse.", claims, agent.numbers_in("what does a $50k order cost?"))
    assert "0.62" in out and "17.3" not in out and dropped == 1


def test_dates_and_times_do_not_count_as_numbers():
    assert agent.numbers_in("On Oct 27 at 15:59 in 2026 the spread was 1.5 bps") == [1.5]


def test_every_tool_runs_on_real_data():
    cov = agent.run_tool("coverage", {})
    last = cov["strike"]["last_ts"]
    assert agent.run_tool("series", {"venue": "strike", "step": "hour", "start": last - 6 * 3600_000, "end": last})["points"]
    for name, args in (("gaps", {"limit": 5}), ("resilience", {"hours": 24}), ("toxicity", {"hours": 24}), ("cancel_fill", {"step": "hour", "hours": 6})):
        assert agent.run_tool(name, args) is not None


def test_hmem_rejects_records_without_source_or_provenance(tmp_path, monkeypatch):
    from follow import hmem
    monkeypatch.setattr(hmem, "PATH", str(tmp_path / "m.json"))
    with pytest.raises(ValueError):
        hmem.add("x", source="", confidence=0.7, provenance={"a": 1})
    with pytest.raises(ValueError):
        hmem.add("x", source="s", confidence=0.7, provenance={})


def test_hmem_supersedes_and_recalls_newest(tmp_path, monkeypatch):
    from follow import hmem
    monkeypatch.setattr(hmem, "PATH", str(tmp_path / "m.json"))
    old = hmem.add("Strike slippage at 50k order (value 0.58)", source="t", confidence=0.9, provenance={"k": 1}, tags=["scorecard", "strike"])
    new = hmem.add("Strike slippage at 50k order (value 0.71)", source="t", confidence=0.9, provenance={"k": 2}, tags=["scorecard", "strike"])
    assert new["supersedes"] == old["id"]
    got = hmem.recall("how is Strike slippage for a 50k order now", k=2)
    assert got and got[0]["id"] == new["id"]


def test_zetaris_tool_is_hidden_until_configured(monkeypatch):
    for k in ("ZETARIS_ORG_ID", "ZETARIS_USERNAME", "ZETARIS_PASSWORD", "ZETARIS_API_KEY", "ZETARIS_SAMPLES_TABLE"):
        monkeypatch.delenv(k, raising=False)
    assert "zetaris_depth_summary" not in agent.tools()


def test_zetaris_sql_is_parameterised_and_rejects_injection():
    from follow import zetaris
    sql = zetaris.depth_summary_sql("follow.book_samples", "strike", 1000, 2000)
    assert "venue = 'strike'" in sql and "ts >= 1000" in sql and "ts < 2000" in sql
    with pytest.raises(ValueError):
        zetaris.depth_summary_sql("book_samples; DROP TABLE x", "strike", 1, 2)
    with pytest.raises(ValueError):
        zetaris.depth_summary_sql("t", "strike' OR '1'='1", 1, 2)
