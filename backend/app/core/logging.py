"""Central logging config. Called once from create_app(). Idempotent (basicConfig only
installs a handler if the root has none), so repeated calls in tests are harmless."""
import logging

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # quiet chatty libraries; our own loggers stay at the configured level
    for noisy in ("httpx", "httpcore", "apscheduler.scheduler", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
