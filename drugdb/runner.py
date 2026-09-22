"""Планировщик синхронизации справочника.

ГРЛС запускается ежедневно в 03:00 по TZ контейнера (по умолчанию Europe/Moscow).
МДЛП проверяется в тот же цикл; фактическая дата публикации может отличаться.
"""
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loader import main

LOG = logging.getLogger("drugdb.runner")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s [drugdb] %(message)s")

RUN_ON_START = os.getenv("DRUGDB_RUN_ON_START", "true").lower() == "true"
RUN_HOUR = int(os.getenv("DRUGDB_RUN_HOUR", "3"))
RUN_MINUTE = int(os.getenv("DRUGDB_RUN_MINUTE", "0"))
TZ_NAME = os.getenv("TZ", "Europe/Moscow")


def _run(source):
    env_name = "GRLS_EXPORT_URL" if source == "grls" else "MDLP_EXPORT_URL"
    if not os.getenv(env_name, "").strip():
        LOG.warning("%s skipped: %s is not configured", source, env_name)
        return
    try:
        import sys
        sys.argv = ["loader.py", source]
        main()
    except Exception:
        LOG.exception("%s import failed", source)


def _seconds_until_next_run():
    tz = ZoneInfo(TZ_NAME)
    now = datetime.now(tz)
    target = now.replace(hour=RUN_HOUR, minute=RUN_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1, int((target - now).total_seconds()))


if __name__ == "__main__":
    if RUN_ON_START:
        for source in ("grls", "mdlp"):
            _run(source)

    while True:
        delay = _seconds_until_next_run()
        LOG.info("next drug database update in %s seconds at %02d:%02d %s",
                 delay, RUN_HOUR, RUN_MINUTE, TZ_NAME)
        time.sleep(delay)
        for source in ("grls", "mdlp"):
            _run(source)
