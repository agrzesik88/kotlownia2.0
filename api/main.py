from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Panel WWW Kotłownia 2.0")
    parser.add_argument("--config", type=Path, default=Path("config/settings.toml"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    uvicorn.run(create_app(args.config), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
