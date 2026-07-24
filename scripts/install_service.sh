#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_TEMPLATE="$PROJECT_DIR/systemd/kotlownia.service.template"
SERVICE_TARGET="/etc/systemd/system/kotlownia.service"
WEB_TEMPLATE="$PROJECT_DIR/systemd/kotlownia-web.service.template"
WEB_TARGET="/etc/systemd/system/kotlownia-web.service"
RUN_USER="${SUDO_USER:-$USER}"
RUN_GROUP="$(id -gn "$RUN_USER")"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "Brak środowiska Python: $PYTHON" >&2
    echo "Najpierw utwórz .venv i zainstaluj requirements.txt." >&2
    exit 1
fi

"$PYTHON" -m controller.main \
    --config "$PROJECT_DIR/config/settings.toml" \
    --check-config

if [[ ! -f "$PROJECT_DIR/config/kotlownia.env" ]]; then
    cp "$PROJECT_DIR/config/kotlownia.env.example" \
       "$PROJECT_DIR/config/kotlownia.env"
    chmod 600 "$PROJECT_DIR/config/kotlownia.env"
fi

TEMP_SERVICE="$(mktemp)"
TEMP_WEB_SERVICE="$(mktemp)"
trap 'rm -f "$TEMP_SERVICE" "$TEMP_WEB_SERVICE"' EXIT

sed \
    -e "s|__USER__|$RUN_USER|g" \
    -e "s|__GROUP__|$RUN_GROUP|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$SERVICE_TEMPLATE" > "$TEMP_SERVICE"

sed \
    -e "s|__USER__|$RUN_USER|g" \
    -e "s|__GROUP__|$RUN_GROUP|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$WEB_TEMPLATE" > "$TEMP_WEB_SERVICE"

sudo install -m 0644 "$TEMP_SERVICE" "$SERVICE_TARGET"
sudo install -m 0644 "$TEMP_WEB_SERVICE" "$WEB_TARGET"
sudo systemctl daemon-reload
sudo systemctl enable kotlownia.service kotlownia-web.service

echo
echo "Usługa zainstalowana i włączona przy starcie systemu."
echo "Uruchom: sudo systemctl restart kotlownia.service kotlownia-web.service"
echo "Status:   systemctl status kotlownia.service"
echo "Logi:     journalctl -u kotlownia.service -f"
echo "WWW:      http://$(hostname -I | awk '{print $1}'):8088"
echo "Panel:    systemctl status kotlownia-web.service"
