"""Regression tests for pipeline logging configuration."""

import subprocess
import sys
from pathlib import Path


def run_logging_probe(script: str, *args: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script, *(str(arg) for arg in args)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_setup_logging_writes_to_console_and_file(tmp_path):
    result = run_logging_probe(
        """
import logging
import sys
from pathlib import Path
from src.logging_setup import setup_logging

log_path = setup_logging("probe", Path(sys.argv[1]))
logging.info("probe message")
print(log_path)
""",
        tmp_path,
    )

    log_path = Path(result.stdout.strip())
    assert log_path.parent == tmp_path
    assert "probe message" in result.stderr
    assert "probe message" in log_path.read_text(encoding="utf-8")


def test_setup_logging_replaces_handlers_without_duplicate_messages(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    result = run_logging_probe(
        """
import logging
import sys
from pathlib import Path
from src.logging_setup import setup_logging

first_log = setup_logging("first", Path(sys.argv[1]))
logging.info("first destination")
second_log = setup_logging("second", Path(sys.argv[2]))
logging.info("after reconfigure")
print(first_log)
print(second_log)
""",
        first_dir,
        second_dir,
    )

    first_log, second_log = map(Path, result.stdout.splitlines())
    assert "after reconfigure" not in first_log.read_text(encoding="utf-8")
    assert "after reconfigure" in second_log.read_text(encoding="utf-8")
    assert result.stderr.count("after reconfigure") == 1
