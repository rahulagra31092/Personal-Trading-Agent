import csv
from pathlib import Path

_HOLDINGS_PATH = Path(__file__).parent / "holdings.csv"


def load_holdings(path: str | None = None) -> list[dict]:
    target = Path(path) if path else _HOLDINGS_PATH
    if not target.exists():
        return []
    holdings = []
    with target.open(newline="") as f:
        for row in csv.DictReader(f):
            holdings.append({
                "ticker": row["ticker"].strip().upper(),
                "shares": float(row["shares"]),
                "cost_basis": float(row["cost_basis"]),
            })
    return holdings


def save_holdings(holdings: list[dict], path: str | None = None) -> None:
    target = Path(path) if path else _HOLDINGS_PATH
    with target.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "shares", "cost_basis"])
        writer.writeheader()
        writer.writerows(holdings)
