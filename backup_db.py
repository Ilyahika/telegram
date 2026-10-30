"""Usage: python backup_db.py /safe/location/backup.db"""
import sqlite3
import sys
from pathlib import Path
from config import DB_PATH
if __name__ == '__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python backup_db.py /safe/location/backup.db')
    target=Path(sys.argv[1]).resolve()
    if not DB_PATH.exists():raise SystemExit('Source database does not exist')
    if target==DB_PATH.resolve() or target.exists():raise SystemExit('Choose a new backup path')
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB_PATH) as src,sqlite3.connect(target) as dst:src.backup(dst)
    print(f'Backup saved: {target}')
