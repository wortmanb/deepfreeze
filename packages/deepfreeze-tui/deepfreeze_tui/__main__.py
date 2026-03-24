"""Entry point for deepfreeze-tui."""

import argparse
import sys
from pathlib import Path

from .app import DeepfreezeApp

DEFAULT_CONFIG_PATH = Path.home() / ".deepfreeze" / "config.yml"


def get_default_config():
    if DEFAULT_CONFIG_PATH.is_file():
        return str(DEFAULT_CONFIG_PATH)
    return None


def main():
    parser = argparse.ArgumentParser(
        prog="deepfreeze-tui",
        description="Terminal UI for deepfreeze",
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to configuration file (default: ~/.deepfreeze/config.yml)",
        default=None,
    )
    parser.add_argument(
        "--refresh", "-r",
        type=int,
        help="Status refresh interval in seconds (default: 30)",
        default=30,
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local mode (direct ES connection) even if a server URL is configured",
        default=False,
    )
    parser.add_argument(
        "--server-url",
        help="URL of the deepfreeze-server (overrides config file)",
        default=None,
    )

    args = parser.parse_args()

    config_path = args.config or get_default_config()

    if not config_path:
        print(
            "ERROR: No config file found. Please provide --config or create ~/.deepfreeze/config.yml"
        )
        sys.exit(1)

    app = DeepfreezeApp(
        config_path=config_path,
        refresh_interval=args.refresh,
        local=args.local,
        server_url=args.server_url,
    )
    app.run()


if __name__ == "__main__":
    main()
