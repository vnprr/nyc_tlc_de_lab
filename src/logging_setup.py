import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def setup_logging(run_name: str, log_dir: Path | None = None) -> Path:
    """Configure UTC console and file logging for one pipeline run.

    The filename includes microseconds and the process ID so two concurrent or
    rapidly repeated runs cannot accidentally share a log file.
    """
    if re.fullmatch(r"[A-Za-z0-9_.-]+", run_name) is None:
        raise ValueError("run_name may contain only letters, digits, dots, underscores and hyphens")

    if log_dir is None:
        log_dir = PROJECT_LOG_DIR

    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    log_path = log_dir / f"{run_name}_{timestamp}_{os.getpid()}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time.gmtime

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    console_handler = logging.StreamHandler()
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.INFO,
        force=True,
        handlers=[file_handler, console_handler],
    )

    logging.getLogger(__name__).info("Log file: %s", log_path)
    return log_path
