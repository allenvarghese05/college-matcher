from __future__ import annotations

import json

import pytest

from app.core.cost import PRICES, cost_usd


def test_sonnet_prices() -> None:
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 0, 0) == pytest.approx(2.00)
    assert cost_usd("claude-sonnet-5-5", 0, 1_000_000, 0) == pytest.approx(10.00)
    assert cost_usd("claude-sonnet-5-5", 0, 0, 1_000_000) == pytest.approx(0.10)


def test_opus_prices() -> None:
    assert cost_usd("claude-opus-5-5", 1_000_000, 0, 0) == pytest.approx(4.00)
    assert cost_usd("claude-opus-5-5", 0, 1_000_000, 0) == pytest.approx(20.00)
    assert cost_usd("claude-opus-5-5", 0, 0, 1_000_000) == pytest.approx(0.20)


def test_mixed_turn() -> None:
    # 1,200 in, 300 out, 8,000 cache read on Sonnet
    expected = (1200 * 2 + 300 * 10 + 8000 * 0.10) / 1_000_000
    assert cost_usd("claude-sonnet-5-5", 1200, 300, 8000) == pytest.approx(expected)


def test_zero_tokens_is_free() -> None:
    assert cost_usd("claude-opus-5-5") == 0.0


def test_unknown_model_raises() -> None:
    with pytest.raises(KeyError):
        cost_usd("gpt-whatever", 10, 10)


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValueError):
        cost_usd("claude-sonnet-5-5", -1, 0)


def test_configured_models_have_prices() -> None:
    from app.core.config import get_settings

    s = get_settings()
    assert s.MODEL_FAST in PRICES
    assert s.MODEL_STRONG in PRICES


def test_turn_logger_stage_records_cost(capsys: pytest.CaptureFixture[str]) -> None:
    from app.core.logging import TurnLogger, configure_logging

    configure_logging()
    tl = TurnLogger(session_id="s1", turn_id="t1")
    with tl.stage("extract") as st:
        st.record_usage(model="claude-sonnet-5-5", input_tokens=1000, output_tokens=100)
    rec = tl.stages[0]
    assert rec["stage"] == "extract"
    assert rec["ms"] >= 0
    assert rec["cost_usd"] == pytest.approx((1000 * 2 + 100 * 10) / 1_000_000)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["session_id"] == "s1" and line["stage"] == "extract"


def test_redact_hides_text_by_default() -> None:
    from app.core.logging import redact

    assert redact("my GPA is 3.9", log_pii=False) == {"len": 13}
    assert redact("my GPA is 3.9", log_pii=True) == "my GPA is 3.9"
