#!/usr/bin/env python3
import os, sqlite3, datetime

src = os.getenv("DATABASE_PATH", "/data/medical_diary.db")
backup_dir = os.getenv("BACKUP_DIR", "/backups")
if not os.path.exists(src):
    raise SystemExit(f"Source not found: {src}")
os.makedirs(backup_dir, exist_ok=True)
dst = os.path.join(backup_dir, f"medical_diary_{datetime.datetime.now():%Y%m%d_%H%M%S}.db")
s = sqlite3.connect(src); d = sqlite3.connect(dst)
with d: s.backup(d)
s.close(); d.close()
print(f"Backup: {dst}")
