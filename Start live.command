#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
printf '%s\n' 'Walnuts Roastery — live local workspace' 'Open http://127.0.0.1:8765. Keep this terminal open while using the app.'
exec python3 -m server.app --db data/production.sqlite --host 127.0.0.1 --port 8765
