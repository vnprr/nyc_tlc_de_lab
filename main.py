"""Sequential orchestrator for the NYC TLC data lake pipeline.

Runs the numbered pipeline steps in dependency order, one after another.
Each step runs as a separate process, which mirrors how real orchestrators
(Airflow, Dagster) execute tasks: isolated failures, memory released between
steps, and one log file per step.

Why subprocess instead of imports: module names cannot start with a digit,
so `import 04_clean_to_processed` is a syntax error. When this pipeline moves
to Airflow, step logic will be extracted into src/ functions called directly
by the DAG - see README "Future work".

Usage:
    python main.py                      # run the whole pipeline
    python main.py --list               # show steps without running anything
    python main.py --only clean         # run a single step
    python main.py --from weather       # resume from a step (after a failure)
    python main.py --force              # pass --force to steps that support it
    python main.py --dry-run            # show the plan, execute nothing
"""

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from src.logging_setup import setup_logging

PROJECT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Step:
    """One pipeline step. Frozen: the pipeline definition must not mutate."""

    name: str
    script: str
    description: str
    supports_force: bool = False


# Dependency order. NOTE: 02_profile_source.py is intentionally absent - it is
# a diagnostic tool for inspecting a single file, not a production step.
STEPS: list[Step] = [
    Step(
        name="download",
        script="01_download_raw.py",
        description="Download raw TLC parquet files to the local raw folder",
    ),
    Step(
        name="upload",
        script="03_upload_raw_to_s3.py",
        description="Upload local raw files into the S3 raw zone (skip existing)",
    ),
    Step(
        name="clean",
        script="04_clean_to_processed.py",
        description="Validate, clean and partition taxi data into processed",
        supports_force=True,
    ),
    Step(
        name="weather",
        script="05_ingest_weather.py",
        description="Fetch hourly weather JSON into the S3 raw zone",
        supports_force=True,
    ),
    Step(
        name="weather_process",
        script="06_process_weather.py",
        description="Convert raw weather JSON into partitioned parquet",
    ),
    Step(
        name="analytics",
        script="07_build_analytics.py",
        description="Build hourly trips + weather analytics tables",
    ),
]

STEP_NAMES = [step.name for step in STEPS]


class StepFailed(RuntimeError):
    """Raised when a pipeline step exits with a non-zero return code."""


def run_step(step: Step, force: bool = False) -> float:
    """Run one step as a subprocess. Returns elapsed seconds, raises on failure."""
    command = [sys.executable, str(PROJECT_DIR / step.script)]
    if force and step.supports_force:
        command.append("--force")

    logging.info("--- STEP %s: %s ---", step.name, step.description)
    logging.info("RUN %s", " ".join(command))

    started = time.perf_counter()
    # No capture_output: child stdout/stderr stream straight to the console.
    result = subprocess.run(command, cwd=PROJECT_DIR, check=False)
    elapsed = time.perf_counter() - started

    if result.returncode != 0:
        raise StepFailed(
            f"Step '{step.name}' ({step.script}) failed with exit code "
            f"{result.returncode} after {elapsed:.1f}s"
        )

    logging.info("DONE %s in %.1fs", step.name, elapsed)
    return elapsed


def select_steps(only: str | None, start_from: str | None) -> list[Step]:
    """Resolve --only / --from into the list of steps to execute."""
    if only and start_from:
        raise ValueError("Use either --only or --from, not both.")

    if only:
        matching = [step for step in STEPS if step.name == only]
        if not matching:
            raise ValueError(f"Unknown step '{only}'. Available: {STEP_NAMES}")
        return matching

    if start_from:
        if start_from not in STEP_NAMES:
            raise ValueError(f"Unknown step '{start_from}'. Available: {STEP_NAMES}")
        return STEPS[STEP_NAMES.index(start_from) :]

    return list(STEPS)


def print_steps() -> None:
    """Print the pipeline plan without running anything."""
    print("\nPipeline steps (in order):\n")
    for index, step in enumerate(STEPS, start=1):
        force_hint = "  [--force]" if step.supports_force else ""
        print(f"  {index}. {step.name:<16} {step.script:<26}{force_hint}")
        print(f"     {step.description}")
    print()


def log_summary(results: list[tuple[str, str, float]], total: float) -> None:
    """Log a per-step status table - the poor man's DAG view."""
    logging.info("=" * 62)
    logging.info("%-18s %-10s %10s", "STEP", "STATUS", "DURATION")
    logging.info("-" * 62)
    for name, status, elapsed in results:
        logging.info("%-18s %-10s %9.1fs", name, status, elapsed)
    logging.info("-" * 62)
    logging.info("%-18s %-10s %9.1fs", "TOTAL", "", total)
    logging.info("=" * 62)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list", action="store_true", help="list pipeline steps and exit"
    )
    parser.add_argument(
        "--only", default=None, metavar="STEP", help=f"run one step: {STEP_NAMES}"
    )
    parser.add_argument(
        "--from",
        dest="start_from",
        default=None,
        metavar="STEP",
        help="resume the pipeline from this step onwards",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="pass --force to steps that support reprocessing",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would run, execute nothing"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list:
        print_steps()
        return 0

    setup_logging("pipeline")
    steps = select_steps(args.only, args.start_from)

    logging.info("Pipeline plan: %s", " -> ".join(step.name for step in steps))
    if args.force:
        logging.info(
            "Force mode ON for steps: %s",
            [step.name for step in steps if step.supports_force],
        )

    if args.dry_run:
        logging.info("Dry run: nothing was executed.")
        return 0

    results: list[tuple[str, str, float]] = []
    pipeline_started = time.perf_counter()

    for index, step in enumerate(steps):
        try:
            elapsed = run_step(step, force=args.force)
        except StepFailed as error:
            results.append((step.name, "FAILED", 0.0))
            for skipped in steps[index + 1 :]:
                results.append((skipped.name, "SKIPPED", 0.0))
            logging.error("%s", error)
            log_summary(results, time.perf_counter() - pipeline_started)
            logging.error(
                "Fix the problem, then resume with: python main.py --from %s",
                step.name,
            )
            return 1
        results.append((step.name, "OK", elapsed))

    log_summary(results, time.perf_counter() - pipeline_started)
    logging.info("Pipeline finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())