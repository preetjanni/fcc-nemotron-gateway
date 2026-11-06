#!/usr/bin/env bash
# Render start script: fcc-server on internal port 8082 + basic-auth
# reverse proxy on Render's public $PORT. PROXY_PASSWORD must be set as
# an environment variable in the Render dashboard (never in a file).
set -e
echo "== starting fcc-server on internal port 8082 =="
PORT=8082 nohup fcc-server > fcc-server.log 2>&1 &
echo "== waiting for fcc-server =="
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8082/ > /dev/null 2>&1; then echo "fcc-server is up"; break; fi
  sleep 2
done
curl -sf http://127.0.0.1:8082/ | head -c 200; echo
echo "== starting auth proxy on public port ${PORT} =="
python3 proxy.py
