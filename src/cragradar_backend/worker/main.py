"""Entry point of the ingest worker: ``cragradar-worker``.

With ``WORKER_RELOAD=true`` (set by the dev image) the worker restarts when the code changes.
"""

import asyncio
import logging
import os
from pathlib import Path

import cragradar_backend
from cragradar_backend.core.database import get_session_factory
from cragradar_backend.core.settings import get_settings
from cragradar_backend.worker.jobs import run_worker

RELOAD_ENVIRONMENT_VARIABLE: str = "WORKER_RELOAD"


def run() -> None:
    """Configure logging and run the worker until the process is stopped."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run_worker(session_factory=get_session_factory(), settings=get_settings()))


def main() -> None:
    """Run the worker, restarting it on code changes when reload is enabled."""
    is_reload_enabled: bool = os.environ.get(RELOAD_ENVIRONMENT_VARIABLE, "").lower() == "true"
    if not is_reload_enabled:
        run()
        return
    import watchfiles

    package_dir: Path = Path(cragradar_backend.__file__).parent
    watchfiles.run_process(package_dir, target=run)
