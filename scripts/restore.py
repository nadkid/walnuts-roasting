#!/usr/bin/env python3
"""Restore into a NEW path only. Stop the app before selecting the restored path."""
import argparse, sqlite3
from backup import backup

def restore(source,destination):
    result=backup(source,destination)
    db=sqlite3.connect(result)
    try:db.execute('DELETE FROM sessions');db.commit()
    finally:db.close()
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('backup');p.add_argument('new_database');a=p.parse_args();print(restore(a.backup,a.new_database))
