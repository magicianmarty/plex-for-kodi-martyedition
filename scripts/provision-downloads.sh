#!/usr/bin/env bash
# Pull the *arr API keys off the media server and write downloads.json onto the
# Kodi box, so nothing has to be typed with a remote. Re-run it after a reflash.
#
#   ./scripts/provision-downloads.sh <kodi-host> <media-host> [qbt-user] [qbt-pass]
#
# Reads: /var/lib/{sonarr,radarr}/config.xml on the media host (systemd layout;
# for Docker point ARR_CONFIG_DIR at the mapped config volume instead).
set -euo pipefail

KODI_HOST="${1:?usage: provision-downloads.sh <kodi-host> <media-host> [qbt-user] [qbt-pass]}"
MEDIA_HOST="${2:?missing media host}"
QBT_USER="${3:-}"
QBT_PASS="${4:-}"

# The hosts are ssh targets, so they may carry a user; a URL must not.
MEDIA_ADDR="${MEDIA_HOST##*@}"

KODI_SSH="${KODI_SSH:-ssh}"
MEDIA_SSH="${MEDIA_SSH:-ssh}"
ARR_CONFIG_DIR="${ARR_CONFIG_DIR:-/var/lib}"
PROFILE="${PROFILE:-/storage/.kodi/userdata/addon_data/script.plexmod}"

read_key() {
    # shellcheck disable=SC2029  # $1 must expand here, on purpose
    $MEDIA_SSH "$MEDIA_HOST" "grep -o '<ApiKey>[^<]*' $ARR_CONFIG_DIR/$1/config.xml 2>/dev/null | cut -d'>' -f2" || true
}

read_port() {
    $MEDIA_SSH "$MEDIA_HOST" "grep -o '<Port>[^<]*' $ARR_CONFIG_DIR/$1/config.xml 2>/dev/null | head -1 | cut -d'>' -f2" || true
}

SONARR_KEY=$(read_key sonarr)
RADARR_KEY=$(read_key radarr)
SONARR_PORT=$(read_port sonarr); SONARR_PORT=${SONARR_PORT:-8989}
RADARR_PORT=$(read_port radarr); RADARR_PORT=${RADARR_PORT:-7878}

[ -n "$SONARR_KEY" ] || echo "warning: no Sonarr key found" >&2
[ -n "$RADARR_KEY" ] || echo "warning: no Radarr key found" >&2

# qBittorrent is only written when credentials were given: an entry without
# them is "configured" as far as the add-on is concerned, so it would poll,
# get a 403 and put a permanent error on screen.
QBT_ENTRY=""
if [ -n "$QBT_USER" ]; then
    QBT_ENTRY=",
  \"qbittorrent\": {\"url\": \"http://$MEDIA_ADDR:8080\", \"user\": \"$QBT_USER\", \"pass\": \"$QBT_PASS\"}"
fi

JSON=$(cat <<JSONEOF
{
  "sonarr": {"url": "http://$MEDIA_ADDR:$SONARR_PORT", "key": "$SONARR_KEY"},
  "radarr": {"url": "http://$MEDIA_ADDR:$RADARR_PORT", "key": "$RADARR_KEY"}$QBT_ENTRY
}
JSONEOF
)

$KODI_SSH "$KODI_HOST" "mkdir -p '$PROFILE' && cat > '$PROFILE/downloads.json' && chmod 600 '$PROFILE/downloads.json'" <<<"$JSON"
echo "wrote $PROFILE/downloads.json on $KODI_HOST (sonarr key: ${#SONARR_KEY} chars, radarr: ${#RADARR_KEY})"
