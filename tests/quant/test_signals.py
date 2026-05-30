from quant.signals import compute_signal


def test_buy_signal_above_threshold():
    result = compute_signal(technical_score=0.9, arima_score=0.9,
                            smart_money_score=0.9, news_score=0.9, earnings_score=0.9)
    assert result["label"] == "BUY"
    assert result["composite_score"] > 0.65


def test_avoid_signal_below_threshold():
    result = compute_signal(technical_score=0.1, arima_score=0.1,
                            smart_money_score=0.1, news_score=0.1, earnings_score=0.1)
    assert result["label"] == "AVOID"
    assert result["composite_score"] < 0.40


def test_watch_signal_at_midpoint():
    result = compute_signal(technical_score=0.5, arima_score=0.5,
                            smart_money_score=0.5, news_score=0.5, earnings_score=0.5)
    assert result["label"] == "WATCH"


def test_returns_layer_scores_dict():
    result = compute_signal(technical_score=0.7, arima_score=0.6)
    assert result["layer_scores"]["technical"] == 0.7
    assert result["layer_scores"]["smart_money"] == 0.5


def test_technical_only_weight_is_030():
    result = compute_signal(technical_score=1.0, arima_score=0.0,
                            smart_money_score=0.0, news_score=0.0, earnings_score=0.0)
    assert abs(result["composite_score"] - 0.30) < 0.0001
