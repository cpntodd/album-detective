from app.config_store import ConfigStore
from app.runtime import get_runtime_paths, setup_logging
from app.ui import run_app


if __name__ == "__main__":
    runtime_paths = get_runtime_paths()
    logger = setup_logging(runtime_paths.logs_dir)
    config_store = ConfigStore(runtime_paths.config_dir / "settings.json", logger)
    logger.info("Application starting")
    run_app(paths=runtime_paths, config_store=config_store, logger=logger)
