import logging
from datetime import datetime
from pathlib import Path

def setup_logging(run_name: str, log_dir: Path = Path("logs")) -> Path:
    """
    configure root logger
    Args:
        run_name: name of the run, used in log file name
    Return: 
        path to the log file
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{run_name}_{timestamp}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ]
    )

    logging.info("Log file:", log_path)
    return log_path