from __future__ import annotations

import argparse
from pathlib import Path

from app.config_store import ConfigStore
from app.runtime import get_runtime_paths, setup_logging
from app.ui import run_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--view-csv", dest="view_csv", default="")
    parser.add_argument("--output-dir", dest="output_dir", default="")
    parser.add_argument("--cache-dir", dest="cache_dir", default="")
    parser.add_argument("--jellyfin-base-url", dest="jellyfin_base_url", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_paths = get_runtime_paths()
    logger = setup_logging(runtime_paths.logs_dir)

    if args.view_csv:
        from app.ui.csv_viewer_window import run_csv_viewer

        output_dir = Path(args.output_dir).expanduser() if args.output_dir else runtime_paths.output_dir
        cache_dir = Path(args.cache_dir).expanduser() if args.cache_dir else (runtime_paths.root_dir / "cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        return run_csv_viewer(
            csv_path=Path(args.view_csv).expanduser(),
            output_dir=output_dir,
            cache_dir=cache_dir,
            jellyfin_base_url=args.jellyfin_base_url,
        )

    config_store = ConfigStore(runtime_paths.config_dir / "settings.json", logger)
    logger.info("Application starting")
    run_app(paths=runtime_paths, config_store=config_store, logger=logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
