#!/usr/bin/env bash
# Build the add-on from the current commit and install it on a Kodi box.
#
#   ./scripts/deploy-to-kodi.sh <kodi-host> [addons-dir]
#
# Kodi holds the add-on open, so it is stopped, replaced and started again.
set -euo pipefail

KODI_HOST="${1:?usage: deploy-to-kodi.sh <kodi-host> [addons-dir]}"
ADDONS_DIR="${2:-/storage/.kodi/addons}"
SSH="${SSH:-ssh}"
STOP_CMD="${STOP_CMD:-systemctl stop kodi}"
START_CMD="${START_CMD:-systemctl start kodi}"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

VERSION=$(python3 -c "import xml.etree.ElementTree as ET; print(ET.parse('addon.xml').getroot().get('version'))")
ZIP="$TMP/script.plexmod-$VERSION.zip"
git archive --format=zip --prefix=script.plexmod/ -o "$ZIP" HEAD
echo "built $(basename "$ZIP") ($(du -h "$ZIP" | cut -f1))"

$SSH "$KODI_HOST" "$STOP_CMD || true"
$SSH "$KODI_HOST" "cat > /tmp/script.plexmod.zip" < "$ZIP"
$SSH "$KODI_HOST" "set -e
    cd '$ADDONS_DIR'
    rm -rf script.plexmod.previous
    [ -d script.plexmod ] && mv script.plexmod script.plexmod.previous
    unzip -q -o /tmp/script.plexmod.zip -d '$ADDONS_DIR'
    rm -f /tmp/script.plexmod.zip
    # The generated skin XML is version-specific; make it rebuild on next start.
    rm -f script.plexmod/resources/skins/Main/1080i/script-plex-*.xml"
$SSH "$KODI_HOST" "$START_CMD"
echo "deployed $VERSION to $KODI_HOST (previous build kept as script.plexmod.previous)"
