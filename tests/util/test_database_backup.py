"""Tests for database backup and recovery."""
import pytest
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from util.database_backup import (
    backup_database,
    backup_all_databases,
    cleanup_old_backups,
    get_latest_backup,
    restore_from_backup,
    get_backup_stats,
    ensure_backup_directory,
    get_backup_filename,
)

_ET = timezone(timedelta(hours=-5))


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO test_table (name) VALUES ('test_data')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    """Create a temporary backup directory."""
    backup_path = tmp_path / "backups"
    backup_path.mkdir()
    # Monkeypatch the backup directory
    monkeypatch.setattr(
        "util.database_backup.BACKUP_DIR",
        backup_path,
    )
    return backup_path


class TestBackupDatabase:
    """Test database backup functionality."""

    def test_backup_creates_file(self, temp_db, backup_dir):
        """Backup should create a file in backup directory."""
        backup_path = backup_database(temp_db, verify=False)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.parent == backup_dir
        assert "test_" in backup_path.name
        assert ".db" in backup_path.name

    def test_backup_preserves_data(self, temp_db, backup_dir):
        """Backup should preserve database contents."""
        backup_database(temp_db, verify=False)

        # Verify data in backup
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM test_table WHERE id = 1")
        original_data = cursor.fetchone()
        conn.close()

        # Check backup has same data
        backup_path = get_latest_backup(temp_db.name)
        assert backup_path is not None

        conn = sqlite3.connect(backup_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM test_table WHERE id = 1")
        backup_data = cursor.fetchone()
        conn.close()

        assert original_data == backup_data

    def test_backup_nonexistent_database(self, backup_dir):
        """Backup should handle nonexistent database gracefully."""
        nonexistent = Path("/nonexistent/db.db")
        backup_path = backup_database(nonexistent, verify=False)

        assert backup_path is None

    def test_backup_verification_passes(self, temp_db, backup_dir):
        """Backup with verification should pass for valid database."""
        backup_path = backup_database(temp_db, verify=True)

        assert backup_path is not None
        assert backup_path.exists()

    def test_backup_filename_format(self):
        """Backup filename should include timestamp."""
        filename = get_backup_filename("paper_portfolio.db", timestamp="2026-06-09_12-00-00")

        assert filename == "paper_portfolio_2026-06-09_12-00-00.db"


class TestBackupAll:
    """Test backing up all databases."""

    @patch("util.database_backup.CRITICAL_DATABASES", [])
    @patch("util.database_backup.OPTIONAL_DATABASES", [])
    def test_backup_all_empty_list(self, backup_dir):
        """Backup all should handle empty database list."""
        results = backup_all_databases()

        assert isinstance(results, dict)
        assert len(results) == 0


class TestCleanupOldBackups:
    """Test backup cleanup functionality."""

    def test_cleanup_removes_old_backups(self, backup_dir, tmp_path):
        """Cleanup should remove backups older than retention period."""
        import os
        from datetime import datetime, timedelta, timezone

        _ET = timezone(timedelta(hours=-5))

        # Create old backup with past mtime
        old_backup = backup_dir / "test_2026-01-01_00-00-00.db"
        old_backup.touch()
        # Set file mtime to 60 days ago
        past_time = (datetime.now(_ET) - timedelta(days=60)).timestamp()
        os.utime(old_backup, (past_time, past_time))

        # Create recent backup with current mtime
        recent_backup = backup_dir / "test_2026-06-09_00-00-00.db"
        recent_backup.touch()

        # Cleanup with 30-day retention
        deleted = cleanup_old_backups(retention_days=30)

        # Old backup should be deleted
        assert not old_backup.exists()
        # Recent backup should remain
        assert recent_backup.exists()
        assert deleted == 1

    def test_cleanup_keeps_recent_backups(self, backup_dir):
        """Cleanup should keep backups within retention period."""
        # Create recent backup
        recent_backup = backup_dir / "test_2026-06-09_00-00-00.db"
        recent_backup.touch()

        deleted = cleanup_old_backups(retention_days=30)

        assert recent_backup.exists()
        assert deleted == 0

    def test_cleanup_empty_directory(self, backup_dir):
        """Cleanup should handle empty backup directory."""
        deleted = cleanup_old_backups(retention_days=30)

        assert deleted == 0


class TestGetLatestBackup:
    """Test retrieving latest backup."""

    def test_get_latest_backup_exists(self, backup_dir):
        """Should return the most recent backup."""
        (backup_dir / "paper_portfolio_2026-06-08_00-00-00.db").touch()
        (backup_dir / "paper_portfolio_2026-06-09_00-00-00.db").touch()

        latest = get_latest_backup("paper_portfolio.db")

        assert latest is not None
        assert "2026-06-09" in latest.name

    def test_get_latest_backup_not_found(self, backup_dir):
        """Should return None if no backups found."""
        latest = get_latest_backup("nonexistent.db")

        assert latest is None


class TestRestoreFromBackup:
    """Test database restoration."""

    def test_restore_from_latest_backup(self, temp_db, backup_dir):
        """Restore should restore from latest backup."""
        # Create backup
        backup_path = backup_database(temp_db, verify=False)

        # Corrupt original database
        temp_db.unlink()

        # Restore
        success = restore_from_backup(temp_db)

        assert success is True
        assert temp_db.exists()

    def test_restore_verifies_backup(self, temp_db, backup_dir):
        """Restore should verify backup before restoring."""
        # Create backup
        backup_path = backup_database(temp_db, verify=False)

        # Delete original
        temp_db.unlink()

        # Restore with verification
        success = restore_from_backup(temp_db)

        assert success is True

    def test_restore_missing_backup(self, temp_db, backup_dir):
        """Restore should fail if no backup available."""
        success = restore_from_backup(temp_db)

        assert success is False

    def test_restore_nonexistent_backup_path(self, temp_db, backup_dir):
        """Restore should fail if backup path doesn't exist."""
        nonexistent_backup = backup_dir / "nonexistent.db"
        success = restore_from_backup(temp_db, backup_path=nonexistent_backup)

        assert success is False


class TestBackupStats:
    """Test backup statistics."""

    def test_get_backup_stats_empty(self, backup_dir):
        """Stats should handle empty backup directory."""
        stats = get_backup_stats()

        assert stats["total_backups"] == 0
        assert stats["total_size_mb"] == 0.0
        assert isinstance(stats["databases"], dict)

    def test_get_backup_stats_with_backups(self, backup_dir):
        """Stats should report backup counts and sizes."""
        # Create a backup file manually
        test_backup = backup_dir / "paper_portfolio_2026-06-09_12-00-00.db"
        test_backup.write_bytes(b"test data" * 1000)  # ~9KB

        stats = get_backup_stats()

        # Should find at least the manually created backup
        assert stats["total_backups"] >= 1
        assert stats["total_size_mb"] > 0

    def test_ensure_backup_directory(self, monkeypatch, tmp_path):
        """Should create backup directory if missing."""
        backup_dir = tmp_path / "backups"
        monkeypatch.setattr(
            "util.database_backup.BACKUP_DIR",
            backup_dir,
        )

        ensure_backup_directory()

        assert backup_dir.exists()
        assert backup_dir.is_dir()
