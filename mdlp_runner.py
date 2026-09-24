"""Периодическое обновление публичного справочника МДЛП.

Контейнер имеет доступ только к отдельному тому справочника, а не к медицинской
SQLite БД пользователя.
"""
from __future__ import annotations

import os
import time

from mdlp_import import main
from mdlp_reference import init_reference_db


INTERVAL = max(3600, int(os.getenv("MDLP_UPDATE_INTERVAL_SECONDS", "604800")))
RUN_ON_START = os.getenv("MDLP_RUN_ON_START", "true").strip().lower() in {"1", "true", "yes", "on"}


def run_once():
    try:
        main([])
    except Exception as exc:
        print(f"[mdlp] update failed: {type(exc).__name__}: {exc}", flush=True)


def run_forever():
    init_reference_db()
    if RUN_ON_START:
        run_once()
    while True:
        time.sleep(INTERVAL)
        run_once()


if __name__ == "__main__":
    run_forever()
