"""Entry point for the frozen (PyInstaller) backend binary, used as a Tauri
sidecar. Runs uvicorn in-process (no reload, no multiprocessing) on a fixed
host/port that the frontend and the Tauri shell both expect."""
import logging
import sys
from pathlib import Path

import uvicorn

from app.core.config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    log_file = LOG_DIR / "backend.log"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")]
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    configure_logging()
    from app.main import app  # imported after logging is configured

    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="info")


if __name__ == "__main__":
    main()
