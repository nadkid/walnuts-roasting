#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
export COOKIE_SECURE=0
unset APP_ORIGIN
printf '%s\n' 'Walnuts Roastery — isolated local demo' 'After the server starts, open http://127.0.0.1:8765' 'Keep this terminal open while using the demo. Press Control-C to stop.'
exec python3 -m server.app --demo --db data/demo.sqlite --port 8765
