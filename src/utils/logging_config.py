"""
Structured logging configuration for the research pipeline.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


def setup_logging(
    level: str = "INFO",
    log_dir: str | None = None,
    run_id: str | None = None,
) -> logging.Logger:
    """
    Configure structured logging for the pipeline.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory for log files. If None, logs to stderr only.
        run_id: Unique identifier for this pipeline run.

    Returns:
        Configured root logger.
    """
    logger = logging.getLogger("config_divergence")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rid = run_id or "run"
        fh = logging.FileHandler(
            log_path / f"{rid}_{ts}.log", encoding="utf-8"
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the project root logger."""
    return logging.getLogger(f"config_divergence.{name}")
