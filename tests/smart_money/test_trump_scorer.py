"""
Smoke tests for the deprecated trump_scorer module.

trump_scorer.py is no longer called in the live pipeline — estimate_revisions.py
fills the 7% weight slot instead. This file is kept only to confirm the module
remains importable (no syntax errors or broken dependencies).

See smart_money/estimate_revisions.py and tests/smart_money/test_estimate_revisions.py
for the active implementation and its tests.
"""


def test_trump_scorer_imports_cleanly():
    """Confirm the deprecated module still loads without errors."""
    from smart_money.trump_scorer import compute_trump_policy_score
    assert callable(compute_trump_policy_score)
