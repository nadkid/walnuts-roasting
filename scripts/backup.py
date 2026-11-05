#!/usr/bin/env python3
"""Consistent online SQLite backup; refuse overwrite and verify before returning."""
import argparse, sqlite3, os
from pathlib import Path

def backup(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file():raise ValueError('Source database does not exist.')
    if destination.exists():raise ValueError('Backup destination must be a new file.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);out=sqlite3.connect(destination)
    try:
        src.backup(out)
        if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed.')
    finally:src.close();out.close()
    os.chmod(destination,0o600)
    return str(destination)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('destination');a=p.parse_args();print(backup(a.source,a.destination))
