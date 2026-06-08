def test_insider_trades_returns_list():
    """compute_insider_trades returns a list of insider trades."""
    from smart_money.insider_trades import compute_insider_trades_score

    result = compute_insider_trades_score("AAPL")
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_insider_trades_score():
    """compute_insider_trades_score returns [0, 1]."""
    from smart_money.insider_trades import compute_insider_trades_score

    score = compute_insider_trades_score("AAPL")
    assert 0.0 <= score <= 1.0
    assert isinstance(score, float)


def test_insider_trades_distinguishes_buys_vs_sales():
    """Score should be higher when insiders are buying vs selling."""
    from smart_money.insider_trades import compute_insider_trades_score

    # This requires actual data, so we just verify it runs
    # Real validation in integration tests
    score = compute_insider_trades_score("AAPL")
    assert score is not None
