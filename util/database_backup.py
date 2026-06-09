"""Automated database backup and recovery for SQLite databases.

Manages daily snapshots of critical trading databases:
- paper_portfolio.db: Paper trading positions, trades, outcomes
- historical.db: Historical price/earnings/analyst data
- cache.db: Market data cache (lower priority)

Features:
- Automatic daily snapshots with timestamp
- Retention policy (keep last 30 days)
- Recovery helper for restoring from backup
- Backup integrity verification
"""
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))

# Database paths
DATA_DIR = Path(__file__).parent.parent / "data"
BACKUP_DIR = DATA_DIR / "backups"

# Critical databases (in priority order)
CRITICAL_DATABASES = [
    DATA_DIR / "paper_portfolio.db",  # Primary: paper trading positions
    DATA_DIR / "historical.db",        # Secondary: historical data cache
]

OPTIONAL_DATABASES = [
    DATA_DIR / "cache.db",  # Low priority: market data cache
]

ALL_DATABASES = CRITICAL_DATABASES + OPTIONAL_DATABASES

# Backup retention
BACKUP_RETENTION_DAYS = 30


def ensure_backup_directory() -> Path:
    """Create backup directory if it doesn't exist."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Backup directory: %s", BACKUP_DIR)
    return BACKUP_DIR


def get_backup_filename(db_name: str, timestamp: Optional[str] = None) -> str:
    """
    Generate backup filename with timestamp.

    Args:
        db_name: Database filename (e.g., "paper_portfolio.db")
        timestamp: ISO timestamp (defaults to now in ET)

    Returns:
        Filename like "paper_portfolio_2026-06-09_20-46-32.db"
    """
    if timestamp is None:
        timestamp = datetime.now(_ET).strftime("%Y-%m-%d_%H-%M-%S")

    base_name = db_name.replace(".db", "")
    return f"{base_name}_{timestamp}.db"


def backup_database(
    db_path: Path,
    verify: bool = True,
    compression: bool = False,
) -> Optional[Path]:
    """
    Create a backup of a database file.

    Args:
        db_path: Path to database file
        verify: Verify backup integrity after creation
        compression: Compress backup (future: .db.gz)

    Returns:
        Path to backup file if successful, None otherwise
    """
    if not db_path.exists():
        logger.warning("Database not found: %s", db_path)
        return None

    ensure_backup_directory()
    backup_filename = get_backup_filename(db_path.name)
    backup_path = BACKUP_DIR / backup_filename

    try:
        # For SQLite, use the VACUUM INTO command if possible
        # Otherwise fall back to file copy
        try:
            conn = sqlite3.connect(db_path)
            # VACUUM INTO copies database and optimizes it
            conn.execute(f"VACUUM INTO '{backup_path}'")
            conn.close()
            logger.info("Backed up (VACUUM): %s → %s", db_path.name, backup_filename)
        except sqlite3.OperationalError:
            # Fallback: simple file copy
            shutil.copy2(db_path, backup_path)
            logger.info("Backed up (copy): %s → %s", db_path.name, backup_filename)

        # Verify backup
        if verify:
            if _verify_backup(backup_path):
                logger.info("Backup verified: %s (%.1f KB)", backup_filename, backup_path.stat().st_size / 1024)
                return backup_path
            else:
                logger.error("Backup verification failed: %s", backup_filename)
                backup_path.unlink()  # Delete corrupt backup
                return None
        else:
            return backup_path

    except Exception as exc:
        logger.error("Failed to backup %s: %s", db_path, exc)
        return None


def _verify_backup(backup_path: Path) -> bool:
    """Verify backup database integrity."""
    try:
        conn = sqlite3.connect(backup_path)
        # Run PRAGMA integrity_check
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()

        if result and result[0] == "ok":
            return True
        else:
            logger.warning("Integrity check failed: %s", result)
            return False
    except Exception as exc:
        logger.error("Failed to verify backup: %s", exc)
        return False


def backup_all_databases() -> Dict[str, Optional[Path]]:
    """
    Backup all critical and optional databases.

    Returns:
        Dict mapping db_path → backup_path (or None if failed)
    """
    ensure_backup_directory()
    results = {}
    timestamp = datetime.now(_ET).strftime("%Y-%m-%d_%H-%M-%S")

    for db_path in CRITICAL_DATABASES:
        backup_path = backup_database(db_path, verify=True)
        results[str(db_path)] = backup_path
        if backup_path:
            logger.info("✅ CRITICAL backup: %s", db_path.name)
        else:
            logger.error("❌ CRITICAL backup failed: %s", db_path.name)

    for db_path in OPTIONAL_DATABASES:
        backup_path = backup_database(db_path, verify=False)  # Optional: don't verify
        results[str(db_path)] = backup_path
        if backup_path:
            logger.info("ℹ️  Optional backup: %s", db_path.name)
        else:
            logger.warning("⚠️  Optional backup failed: %s", db_path.name)

    return results


def cleanup_old_backups(retention_days: int = BACKUP_RETENTION_DAYS) -> int:
    """
    Delete backup files older than retention period.

    Args:
        retention_days: Keep backups from last N days

    Returns:
        Number of backups deleted
    """
    if not BACKUP_DIR.exists():
        return 0

    cutoff_date = datetime.now(_ET) - timedelta(days=retention_days)
    deleted_count = 0

    for backup_file in BACKUP_DIR.glob("*.db"):
        try:
            file_stat = backup_file.stat()
            file_mtime = datetime.fromtimestamp(file_stat.st_mtime, tz=_ET)

            if file_mtime < cutoff_date:
                backup_file.unlink()
                deleted_count += 1
                logger.info("Cleaned up old backup: %s", backup_file.name)
        except Exception as exc:
            logger.warning("Failed to clean up %s: %s", backup_file.name, exc)

    if deleted_count > 0:
        logger.info("Cleanup complete: deleted %d old backups (retention: %d days)", deleted_count, retention_days)

    return deleted_count


def get_latest_backup(db_name: str) -> Optional[Path]:
    """
    Get the most recent backup for a database.

    Args:
        db_name: Database filename (e.g., "paper_portfolio.db")

    Returns:
        Path to latest backup, or None if no backups found
    """
    if not BACKUP_DIR.exists():
        return None

    base_name = db_name.replace(".db", "")
    matching_backups = sorted(BACKUP_DIR.glob(f"{base_name}_*.db"), reverse=True)

    return matching_backups[0] if matching_backups else None


def restore_from_backup(
    db_path: Path,
    backup_path: Optional[Path] = None,
) -> bool:
    """
    Restore a database from backup.

    Args:
        db_path: Target database path
        backup_path: Backup to restore from (defaults to latest)

    Returns:
        True if restore successful, False otherwise
    """
    if backup_path is None:
        backup_path = get_latest_backup(db_path.name)

    if backup_path is None:
        logger.error("No backup found for %s", db_path.name)
        return False

    if not backup_path.exists():
        logger.error("Backup file not found: %s", backup_path)
        return False

    try:
        # Verify backup before restoring
        if not _verify_backup(backup_path):
            logger.error("Backup is corrupt, aborting restore: %s", backup_path)
            return False

        # Backup the current database before overwriting
        if db_path.exists():
            backup_current = BACKUP_DIR / f"{db_path.name}.pre-restore"
            shutil.copy2(db_path, backup_current)
            logger.info("Saved pre-restore backup: %s", backup_current.name)

        # Restore
        shutil.copy2(backup_path, db_path)
        logger.info("✅ Restored %s from %s", db_path.name, backup_path.name)
        return True

    except Exception as exc:
        logger.error("Failed to restore from backup: %s", exc)
        return False


def get_backup_stats() -> Dict[str, any]:
    """
    Get statistics on current backups.

    Returns:
        Dict with backup counts and total size
    """
    if not BACKUP_DIR.exists():
        return {
            "total_backups": 0,
            "total_size_mb": 0.0,
            "databases": {},
        }

    stats = {
        "total_backups": 0,
        "total_size_bytes": 0,
        "databases": {},
    }

    for db_name in [db.name for db in CRITICAL_DATABASES + OPTIONAL_DATABASES]:
        base_name = db_name.replace(".db", "")
        backups = list(BACKUP_DIR.glob(f"{base_name}_*.db"))

        db_size = sum(b.stat().st_size for b in backups)
        stats["total_backups"] += len(backups)
        stats["total_size_bytes"] += db_size

        stats["databases"][db_name] = {
            "count": len(backups),
            "size_mb": db_size / (1024 * 1024),
            "latest": backups[0].name if backups else None,
        }

    # Convert to MB for readability
    stats["total_size_mb"] = stats["total_size_bytes"] / (1024 * 1024)

    return stats
