#!/usr/bin/env python3
"""Reset paper_portfolio database to clean state for Phase 1 paper trading."""
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

_ET = timezone(timedelta(hours=-5))

DB_PATH = Path(__file__).parent.parent / "data" / "paper_portfolio.db"
BACKUP_DIR = Path(__file__).parent.parent / "data" / "backups"
STARTING_CAPITAL = 10000.0


def backup_database():
    """Create backup before reset."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(_ET).strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = BACKUP_DIR / f"paper_portfolio_pre_reset_{timestamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"[OK] Backup created: {backup_path}")
    return backup_path


def reset_database():
    """Clear all stray data and reset to Phase 1 starting state."""
    if not DB_PATH.exists():
        print(f"[FAIL] Database not found: {DB_PATH}")
        return False

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Clear transaction history
        cursor.execute("DELETE FROM paper_trades")
        print("[OK] Cleared: paper_trades")

        # Clear corrupted outcomes
        cursor.execute("DELETE FROM signal_outcomes")
        print("[OK] Cleared: signal_outcomes")

        # Clear historical scores
        cursor.execute("DELETE FROM score_history")
        print("[OK] Cleared: score_history")

        # Clear Warren B decisions (if table exists)
        try:
            cursor.execute("DELETE FROM warren_b_decisions")
            print("[OK] Cleared: warren_b_decisions")
        except sqlite3.OperationalError:
            print("[WARN]  warren_b_decisions table doesn't exist yet (OK)")

        # Clear weight changes
        cursor.execute("DELETE FROM weight_changes")
        print("[OK] Cleared: weight_changes")

        # Clear conversation history
        try:
            cursor.execute("DELETE FROM warren_b_conversations")
            print("[OK] Cleared: warren_b_conversations")
        except sqlite3.OperationalError:
            print("[WARN]  warren_b_conversations table doesn't exist yet (OK)")

        # Reset positions (delete all open positions)
        cursor.execute("DELETE FROM paper_positions")
        print("[OK] Cleared: paper_positions (zero positions)")

        # Reset account to starting state
        cursor.execute(
            "UPDATE paper_account SET cash = ? WHERE id = 1",
            (STARTING_CAPITAL,)
        )
        print(f"[OK] Reset: paper_account to ${STARTING_CAPITAL:,.0f} cash")

        conn.commit()
        return True

    except Exception as e:
        print(f"[FAIL] Error during reset: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def verify_clean_state():
    """Verify database is in clean state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    checks = [
        ("Account Capital", "SELECT starting_capital FROM paper_account"),
        ("Account Cash", "SELECT cash FROM paper_account"),
        ("Open Positions", "SELECT COUNT(*) FROM paper_positions"),
        ("Trade History", "SELECT COUNT(*) FROM paper_trades"),
        ("Signal Outcomes", "SELECT COUNT(*) FROM signal_outcomes"),
        ("Score History", "SELECT COUNT(*) FROM score_history"),
    ]

    print("\n" + "="*60)
    print("DATABASE VERIFICATION")
    print("="*60)

    all_good = True
    for name, query in checks:
        try:
            cursor.execute(query)
            result = cursor.fetchone()[0]

            # Validation checks
            if name == "Account Capital" and result != STARTING_CAPITAL:
                print(f"[FAIL] {name:20}: ${result:,.0f} (expected ${STARTING_CAPITAL:,.0f})")
                all_good = False
            elif name == "Account Cash" and result != STARTING_CAPITAL:
                print(f"[FAIL] {name:20}: ${result:,.0f} (expected ${STARTING_CAPITAL:,.0f})")
                all_good = False
            elif name == "Open Positions" and result != 0:
                print(f"[FAIL] {name:20}: {result} (expected 0)")
                all_good = False
            elif name == "Trade History" and result != 0:
                print(f"[FAIL] {name:20}: {result} (expected 0)")
                all_good = False
            elif name == "Signal Outcomes" and result != 0:
                print(f"[FAIL] {name:20}: {result} (expected 0)")
                all_good = False
            elif name == "Score History" and result != 0:
                print(f"[FAIL] {name:20}: {result} (expected 0)")
                all_good = False
            else:
                print(f"[OK] {name:20}: {result}")
        except sqlite3.OperationalError as e:
            print(f"[WARN]  {name:20}: Table not found (OK for new tables)")

    conn.close()
    return all_good


def main():
    print("="*60)
    print("TRADING ANALYST — DATABASE RESET FOR PHASE 1")
    print("="*60)
    print()

    # Step 1: Backup
    print("Step 1: Creating backup...")
    backup_path = backup_database()
    print()

    # Step 2: Reset
    print("Step 2: Resetting database...")
    if not reset_database():
        print("[FAIL] Reset failed")
        return False
    print()

    # Step 3: Verify
    print("Step 3: Verifying clean state...")
    if not verify_clean_state():
        print("\n[FAIL] Verification failed — database may be in inconsistent state")
        return False

    print()
    print("="*60)
    print("[OK] DATABASE RESET COMPLETE")
    print("="*60)
    print(f"Backup: {backup_path}")
    print(f"Status: Ready for Phase 1 paper trading")
    print()
    return True


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
