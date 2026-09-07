#!/usr/bin/env bash
# Screenshot a Kodi box that cannot screenshot itself.
#
#   ./scripts/screenshot.sh root@kodi-box [out.png]
#
# Kodi's own TakeScreenshot fails on Amlogic/GBM ("glReadPixels failed") because
# it renders straight to a DRM plane, and /dev/fb0 holds only the boot splash.
# This copies a reader onto the box, pulls the frame the CRTC is scanning out,
# and brings back a PNG.
set -euo pipefail

HOST="${1:?usage: screenshot.sh <user@host> [out.png]}"
OUT="${2:-shot.png}"
SSH="${SSH:-ssh}"
SCP="${SCP:-scp}"
SCALE="${SCALE:-2}"

$SCP "$(dirname "$0")/kodi-screenshot.py" "$HOST:/tmp/kodi-screenshot.py" >/dev/null
$SSH "$HOST" "SHOT_SCALE=$SCALE python3 /tmp/kodi-screenshot.py /tmp/kodi-shot.png" >/dev/null
$SCP "$HOST:/tmp/kodi-shot.png" "$OUT" >/dev/null
echo "wrote $OUT"
