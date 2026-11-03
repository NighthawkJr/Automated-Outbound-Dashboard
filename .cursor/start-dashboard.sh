#!/usr/bin/env bash
set -euo pipefail

PORT=8080

if python3 - <<'PY'
import socket
s = socket.socket()
try:
    s.bind(("0.0.0.0", 8080))
except OSError:
    raise SystemExit(0)  # already in use — another server is up
finally:
    s.close()
raise SystemExit(1)
PY
then
  echo "Dashboard already listening on port ${PORT}"
  exit 0
fi

exec python3 -m http.server "${PORT}" --bind 0.0.0.0
