#!/usr/bin/env python3
"""Initialize mounted-volume ownership, then run the app without root privileges."""
import os,sys
from pathlib import Path

def main():
    data=Path('/data');data.mkdir(parents=True,exist_ok=True)
    if os.geteuid()==0:
        os.chown(data,10001,10001)
        for name in ('production.sqlite','production.sqlite-wal','production.sqlite-shm'):
            p=data/name
            if p.is_symlink():raise SystemExit('Database paths must not be symlinks.')
            if p.exists():os.chown(p,10001,10001)
        os.setgroups([]);os.setgid(10001);os.setuid(10001)
    os.execvp(sys.argv[1],sys.argv[1:])
if __name__=='__main__':main()
