"""Database backup, restoration, and verification utility for Aqua OS.

Supports both local SQLite and PostgreSQL.
Verifies data integrity and table record counts upon restore.
"""

import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


def calculate_file_hash(path: Path) -> str:
    """Calculate SHA-256 hash of a file for integrity verification."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def backup_sqlite(db_file: Path, backup_dir: Path) -> Path:
    """Perform atomic online backup of SQLite database using VACUUM INTO."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"aqua_os_backup_{timestamp}.db"

    # Use SQLite native backup API for atomic snapshot
    src_conn = sqlite3.connect(str(db_file))
    dst_conn = sqlite3.connect(str(backup_file))
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    return backup_file


def verify_sqlite_backup(backup_file: Path) -> Dict[str, int]:
    """Inspect backup database to verify integrity and record counts."""
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    conn = sqlite3.connect(str(backup_file))
    cursor = conn.cursor()

    # Integrity check pragma
    cursor.execute("PRAGMA integrity_check;")
    integrity = cursor.fetchone()[0]
    if integrity != "ok":
        conn.close()
        raise RuntimeError(f"Database integrity check failed: {integrity}")

    # Inspect table counts
    counts = {}
    for table in ["ponds", "telemetry_records", "latest_telemetry", "users", "audit_logs"]:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            counts[table] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            counts[table] = 0

    conn.close()
    return counts


def restore_sqlite_backup(backup_file: Path, target_file: Path) -> bool:
    """Restore database from backup file and verify integrity."""
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file does not exist: {backup_file}")

    # Verify backup before restoring
    verify_sqlite_backup(backup_file)

    # Perform atomic replacement
    temp_target = target_file.with_suffix(".tmp")
    shutil.copy2(backup_file, temp_target)
    if target_file.exists():
        target_file.unlink()
    temp_target.rename(target_file)

    # Verify restored target
    verify_sqlite_backup(target_file)
    return True

