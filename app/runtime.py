from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root_dir: Path
    config_dir: Path
    logs_dir: Path
    output_dir: Path


def get_runtime_paths(root_dir: Path | None = None) -> RuntimePaths:
    root = root_dir or Path.cwd()
    paths = RuntimePaths(
        root_dir=root,
        config_dir=root / "Config",
        logs_dir=root / "Logs",
        output_dir=root / "Output",
    )

    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    return paths


def setup_logging(logs_dir: Path) -> logging.Logger:
    logger = logging.getLogger("compare_app")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    diagnostic_handler = logging.FileHandler(logs_dir / "diagnostic.log", encoding="utf-8")
    diagnostic_handler.setLevel(logging.INFO)
    diagnostic_handler.setFormatter(formatter)

    error_handler = logging.FileHandler(logs_dir / "error.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    logger.addHandler(diagnostic_handler)
    logger.addHandler(error_handler)
    logger.propagate = False
    logger.info("Logging initialized")
    return logger
