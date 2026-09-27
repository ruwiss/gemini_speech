#!/bin/sh
DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
if [ -x "$DIR/cookie_host" ]; then
  exec "$DIR/cookie_host"
fi
cd "$DIR"
export PYTHONPATH="$DIR"
exec python3 -u "$DIR/cookie_host.py"
