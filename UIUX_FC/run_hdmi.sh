#!/usr/bin/env bash
# Launch UniMate Kivy UI on the Raspberry Pi HDMI desktop (DISPLAY :0).
set -euo pipefail
cd "$(dirname "$0")"
export DISPLAY="${DISPLAY:-:0}"
if [[ -x "$HOME/nlp/bin/python3" ]]; then
  exec "$HOME/nlp/bin/python3" main.py "$@"
else
  exec python3 main.py "$@"
fi
