"""Планировщик ежедневной синхронизации справочника."""
import logging
import os
import time
from datetime import datetime

from loader import main

LOG = logging.getLogger("drugdb.runner")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s [drugdb] %(message)s")

INTERVAL = int(os.getenv("DRUGDB_UPDATE_INTERVAL_SECONDS", "86400"))


def _run(source):
    try:
        import sys
        sys.argv = ["loader.py", source]
        main()
    except Exception:
        LOG.exception("%s import failed", source)


if __name__ == "__main__":
    # Первый запуск — только если URL задан. После этого повторяем раз в сутки.
    while True:
        for source in ("grls", "mdlp"):
            _run(source)
        time.sleep(INTERVAL)
