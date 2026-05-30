from quant.trade_setup import compute_trade_setup


def test_returns_required_keys():
    result = compute_trade_setup(100.0, 90.0)
    for key in ("entry_price", "stop_loss", "take_profit", "risk_per_share",
                "reward_per_share", "risk_reward_ratio"):
        assert key in result


def test_stop_loss_equals_atr_stop():
    result = compute_trade_setup(100.0, 90.0)
    assert result["stop_loss"] == 90.0


def test_risk_per_share_correct():
    result = compute_trade_setup(100.0, 90.0)
    assert result["risk_per_share"] == 10.0


def test_reward_per_share_is_3x_risk():
    result = compute_trade_setup(100.0, 90.0)
    assert result["reward_per_share"] == 30.0


def test_take_profit_correct():
    result = compute_trade_setup(100.0, 90.0)
    assert result["take_profit"] == 130.0


def test_risk_reward_ratio_is_3():
    result = compute_trade_setup(100.0, 90.0)
    assert result["risk_reward_ratio"] == 3.0


def test_entry_price_rounded():
    result = compute_trade_setup(123.456, 110.0)
    assert result["entry_price"] == 123.46


def test_zero_risk_uses_minimum():
    # atr_stop == current_price → risk clamped to 0.01
    result = compute_trade_setup(100.0, 100.0)
    assert result["risk_per_share"] == 0.01
    assert result["risk_reward_ratio"] == 3.0


def test_atr_stop_above_price_clamped():
    # atr_stop > current_price — should not crash
    result = compute_trade_setup(100.0, 105.0)
    assert result["risk_per_share"] == 0.01
    assert result["take_profit"] > result["entry_price"]
