#!/usr/bin/env bash
# Start script: fcc-server on internal port 8082 + basic-auth
# reverse proxy on the host's public $PORT.
# fcc-server's output goes to stdout/stderr (NOT a file) so the host's
# log stream captures it — a file inside the container is invisible.
set -e
echo "== starting fcc-server on internal port 8082 =="
PORT=8082 fcc-server 2>&1 &
echo "== waiting for fcc-server =="
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8082/ > /dev/null 2>&1; then echo "fcc-server is up"; break; fi
  sleep 2
done
curl -sf http://127.0.0.1:8082/ | head -c 200; echo
echo "== starting auth proxy on public port ${PORT} =="
python3 proxy.py
