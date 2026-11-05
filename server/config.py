"""Load local configuration as literal data, without executing shell expressions."""
import os,re,shlex
from pathlib import Path

def load_env(path):
    path=Path(path)
    if not path.is_file():return
    for number,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        if line.startswith('export '):line=line[7:].lstrip()
        key,sep,value=line.partition('=');key=key.strip()
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key):raise ValueError(f'Invalid .env syntax on line {number}.')
        try:parts=shlex.split(value,comments=True,posix=True)
        except ValueError:raise ValueError(f'Invalid .env quoting on line {number}.') from None
        if len(parts)>1:raise ValueError(f'Quote values containing spaces on .env line {number}.')
        os.environ.setdefault(key,parts[0] if parts else '')
