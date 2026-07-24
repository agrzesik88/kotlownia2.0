#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Użycie: $0 /ścieżka/do/poprzedniego/Kotlownia2" >&2
    exit 1
fi

OLD_DIR="$(cd "$1" && pwd)"
NEW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$NEW_DIR/runtime"
for file in state.json history.db history.db-wal history.db-shm schedule.json; do
    if [[ -f "$OLD_DIR/runtime/$file" ]]; then
        cp -a "$OLD_DIR/runtime/$file" "$NEW_DIR/runtime/$file"
        echo "Przeniesiono runtime/$file"
    fi
done

if [[ -f "$OLD_DIR/config/kotlownia.env" && ! -f "$NEW_DIR/config/kotlownia.env" ]]; then
    cp -a "$OLD_DIR/config/kotlownia.env" "$NEW_DIR/config/kotlownia.env"
    chmod 600 "$NEW_DIR/config/kotlownia.env"
    echo "Przeniesiono config/kotlownia.env"
fi
