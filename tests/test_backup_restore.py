"""Automated tests for database backup, restore, and integrity verification."""

from pathlib import Path

from scripts.backup_restore import (
    backup_sqlite,
    restore_sqlite_backup,
    verify_sqlite_backup,
)


def test_sqlite_backup_and_restore(tmp_path: Path):
    """Test full backup, verification, and restore disaster recovery cycle."""
    source_db = Path("aqua_os.db")
    backup_dir = tmp_path / "backups"
    restore_target = tmp_path / "restored_aqua_os.db"

    # 1. Create online atomic backup
    backup_path = backup_sqlite(source_db, backup_dir)
    assert backup_path.exists()

    # 2. Verify backup integrity and table counts
    counts = verify_sqlite_backup(backup_path)
    assert counts["ponds"] >= 20  # Baseline 20 ponds preserved
    assert counts["users"] >= 4  # Users preserved

    # 3. Restore to target location
    success = restore_sqlite_backup(backup_path, restore_target)
    assert success is True
    assert restore_target.exists()

    # 4. Verify restored database has identical valid state
    restored_counts = verify_sqlite_backup(restore_target)
    assert restored_counts == counts

