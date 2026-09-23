"""Планировщик синхронизации справочника лекарств.

ГРЛС проверяется ежедневно в 03:00 по часовому поясу TZ.
МДЛП проверяется с интервалом DRUGDB_UPDATE_INTERVAL_SECONDS (по умолчанию
24 часа). Импорт идемпотентный, поэтому повторная проверка безопасна.
"""
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:\n    from .loader import main\nexcept ImportError:  # запуск как `python drugdb/runner.py`\n    from loader import main

LOG = logging.getLogger("drugdb.runner")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [drugdb] %(message)s",
)

RUN_ON_START = os.getenv("DRUGDB_RUN_ON_START", "true").lower() == "true"
RUN_HOUR = int(os.getenv("DRUGDB_RUN_HOUR", "3"))
RUN_MINUTE = int(os.getenv("DRUGDB_RUN_MINUTE", "0"))
TZ_NAME = os.getenv("TZ", "Europe/Moscow")
UPDATE_INTERVAL = max(60, int(os.getenv("DRUGDB_UPDATE_INTERVAL_SECONDS", "86400")))


def _run(source):
    # МДЛП имеет официальный /data/latest по умолчанию, поэтому отсутствие
    # MDLP_EXPORT_URL не отключает синхронизацию.
    if source == "grls" and not os.getenv("GRLS_EXPORT_URL", "").strip():
        LOG.warning("%s skipped: GRLS_EXPORT_URL is not configured", source)
        return
    try:
        sys.argv = ["loader.py", source]
        main()
    except Exception:
        # Один неудачный источник не должен останавливать планировщик.
        LOG.exception("%s import failed", source)


def _seconds_until_next_grls(now=None):
    tz = ZoneInfo(TZ_NAME)
    now = now or datetime.now(tz)
    target = now.replace(
        hour=RUN_HOUR, minute=RUN_MINUTE, second=0, microsecond=0
    )
    if target <= now:
        target += timedelta(days=1)
    return max(1, int((target - now).total_seconds()))


def _run_start():
    for source in ("grls", "mdlp"):
        _run(source)


def run_forever():
    """Запускает независимые расписания ГРЛС и МДЛП."""
    if RUN_ON_START:
        _run_start()
        next_mdlp = time.monotonic() + UPDATE_INTERVAL
    else:
        next_mdlp = time.monotonic() + UPDATE_INTERVAL

    # ГРЛС всегда привязан к локальному времени 03:00, а не к моменту старта
    # контейнера. Это важно после перезапуска контейнера.
    next_grls = time.monotonic() + _seconds_until_next_grls()

    while True:
        now = time.monotonic()
        if now >= next_grls:
            _run("grls")
            next_grls = time.monotonic() + _seconds_until_next_grls()

        if now >= next_mdlp:
            _run("mdlp")
            next_mdlp = time.monotonic() + UPDATE_INTERVAL

        sleep_for = min(next_grls - time.monotonic(), next_mdlp - time.monotonic())
        time.sleep(max(1, sleep_for))


if __name__ == "__main__":
    run_forever()
