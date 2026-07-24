from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal

from controller.application import ControllerApplication
from controller.config import load_config

# Zgodność ze starszymi importami: tests i zewnętrzny kod mogą nadal importować
# ControllerApplication z controller.main.
__all__ = ["ControllerApplication", "main"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sterownik Kotłownia 2.0")
    parser.add_argument(
        "--config", type=Path, default=Path("config/settings.toml"), help="Plik TOML"
    )
    parser.add_argument("--once", action="store_true", help="Wykonaj jeden cykl i zakończ")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Sprawdź konfigurację i zakończ bez inicjalizacji GPIO",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config)
    if args.check_config:
        print(f"Konfiguracja poprawna: {args.config.resolve()}")
        return 0

    app = ControllerApplication(config)
    signal.signal(signal.SIGTERM, app.request_stop)
    signal.signal(signal.SIGINT, app.request_stop)
    try:
        state = app.run_once() if args.once else (app.run() or app.state)
        if args.once:
            print(state.to_dict())
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
