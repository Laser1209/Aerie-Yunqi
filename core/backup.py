"""Aerie · 云栖 v9.0 — Data backup and migration.

Daily auto-backup to data/backups/aerie_*.zip (7-day retention).
Manual one-click migration to desktop.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class BackupManager:
    """Zip-based backup of data/ + userData/config.json."""

    def __init__(self, data_dir: str = "data", user_data_dir: str = "userData", backups_dir: Optional[str] = None) -> None:
        self.data_dir = Path(data_dir)
        self.user_data_dir = Path(user_data_dir)
        self.backups_dir = Path(backups_dir or (self.data_dir / "backups"))
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self) -> Path:
        """Create a zip of data/*.db + userData/config.json. Return zip path."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = self.backups_dir / f"aerie_{ts}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Data DBs
            for db in self.data_dir.glob("*.db"):
                zf.write(db, arcname=f"data/{db.name}")
            # userData config
            cfg = self.user_data_dir / "config.json"
            if cfg.exists():
                zf.write(cfg, arcname=f"userData/{cfg.name}")
        return zip_path

    def restore_backup(self, zip_path: str | Path) -> bool:
        """Restore data and userData from a zip."""
        zip_path = Path(zip_path)
        if not zip_path.exists():
            return False
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(".")
            return True
        except Exception as e:
            logger.error("restore failed: %s", e)
            return False

    def cleanup_old(self, keep_days: int = 7) -> int:
        """Delete backups older than keep_days. Returns count deleted."""
        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = 0
        for f in self.backups_dir.glob("aerie_*.zip"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except Exception:
                pass
        return deleted

    def auto_backup_daily(self) -> dict:
        """Daily routine: create + cleanup."""
        zip_path = self.create_backup()
        deleted = self.cleanup_old(keep_days=7)
        return {"backup": str(zip_path), "deleted": deleted}

    def migrate_to(self, target_path: str | Path) -> Path:
        """Create a migration zip at target_path, including all data + config."""
        target_path = Path(target_path)
        ts = datetime.now().strftime("%Y%m%d")
        if target_path.is_dir():
            target_path = target_path / f"Aerie-migration-{ts}.zip"
        elif not target_path.suffix:
            target_path = target_path.with_suffix(".zip")
        with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for db in self.data_dir.glob("*.db"):
                zf.write(db, arcname=f"data/{db.name}")
            for sub in self.data_dir.glob("backups/*.zip"):
                zf.write(sub, arcname=f"data/backups/{sub.name}")
            cfg = self.user_data_dir / "config.json"
            if cfg.exists():
                zf.write(cfg, arcname=f"userData/{cfg.name}")
        return target_path
