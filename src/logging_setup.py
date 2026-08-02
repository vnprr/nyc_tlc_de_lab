import logging
from datetime import datetime
from pathlib import Path


PROJECT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def setup_logging(run_name: str, log_dir: Path | None = None) -> Path:
    """Configure console and file logging for one pipeline run."""
    if log_dir is None:
        log_dir = PROJECT_LOG_DIR

    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{run_name}_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    logging.info("Log file: %s", log_path)
    return log_path
