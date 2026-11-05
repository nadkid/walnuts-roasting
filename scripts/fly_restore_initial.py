#!/usr/bin/env python3
"""Restore the first hosted database only into an empty, unconnected installation."""
import argparse,json,os,sqlite3
from pathlib import Path

def restore(source,destination):
    if any(os.getenv(k) for k in ('ROASTWORLD_API_KEY','SHOPIFY_SHOP','SQUARE_ACCESS_TOKEN')):
        raise ValueError('Import the database before configuring provider credentials.')
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination or not source.is_file():raise ValueError('Choose a separate existing migration snapshot.')
    src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);out=sqlite3.connect(destination)
    try:
        if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or src.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Migration snapshot failed integrity checks.')
        if json.loads(src.execute("SELECT value FROM settings WHERE key='demo'").fetchone()[0]):raise ValueError('Demo data cannot initialize hosted production.')
        for table in ('users','movements','orders'):
            if out.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() and out.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]:raise ValueError('Hosted database contains operational data; refusing overwrite.')
        src.backup(out)
        out.execute('DELETE FROM sessions');out.commit()
        if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Restored database failed integrity check.')
    finally:src.close();out.close()
    os.chmod(destination,0o600)
    if os.geteuid()==0:
        owner=destination.parent.stat()
        for name in (destination,Path(str(destination)+'-wal'),Path(str(destination)+'-shm')):
            if name.exists():os.chown(name,owner.st_uid,owner.st_gid)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('destination');a=p.parse_args();restore(a.source,a.destination);print('Initial database imported; sign in again on the hosted app.')
