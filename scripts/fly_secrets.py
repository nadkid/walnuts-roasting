#!/usr/bin/env python3
"""Transfer only provider credentials to Fly secrets through stdin, never arguments."""
import argparse,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.config import load_env
KEYS=('ROASTWORLD_API_KEY','SHOPIFY_SHOP','SHOPIFY_CLIENT_ID','SHOPIFY_CLIENT_SECRET',
      'SHOPIFY_ACCESS_TOKEN','SHOPIFY_WEBHOOK_SECRET','SQUARE_ACCESS_TOKEN','SQUARE_ENVIRONMENT')
def main():
    p=argparse.ArgumentParser();p.add_argument('--fly',default='fly');p.add_argument('--app',required=True);p.add_argument('--env',default='.env');p.add_argument('--stage',action='store_true');a=p.parse_args()
    load_env(a.env)
    values={k:os.environ[k] for k in KEYS if os.environ.get(k)}
    if not values:raise SystemExit('No provider credentials found.')
    if any('\n' in v or '\r' in v for v in values.values()):raise SystemExit('Credential values must be single-line.')
    subprocess.run([a.fly,'secrets','import','--app',a.app]+(['--stage'] if a.stage else []),input=''.join(k+'='+v+'\n' for k,v in values.items()),text=True,check=True)
if __name__=='__main__':main()
