"""Импорт официальной CSV-выгрузки МДЛП в отдельную SQLite БД.

Импорт транзакционный и идемпотентный: при ошибке старая версия справочника
остаётся целой. Медицинская БД приложения при этом не открывается.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone

from mdlp_reference import REFERENCE_DB, init_reference_db

EXPECTED_COLUMNS = [
    "gtin", "prod_name", "prod_norm_name", "prod_desc", "prod_sell_name",
    "reg_id", "reg_date", "reg_holder", "prod_d_name", "prod_d_norm_name",
    "mass_volume_name", "prod_form_name", "prod_form_norm_name",
    "prod_pack_1_desc", "prod_pack_1_2", "prod_pack_1_name",
    "prod_pack_1_size", "completeness", "cost_limit", "glf_name",
    "glf_country", "gnvlp", "narcotic", "is_vzn_drug", "inn", "reg_status",
]

DEFAULT_URL = os.getenv(
    "MDLP_EXPORT_URL",
    "https://xn--80aaani3am7aog.xn--80ajghhoc2aj1c8b.xn--p1ai/bi/api/opendata/7731376812-MDLPGtins/data/latest",
).strip()


def _normalise_gtin(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 13:
        digits = "0" + digits
    if len(digits) != 14:
        raise ValueError("GTIN должен содержать 13 или 14 цифр")
    total = sum(int(d) * (3 if pos % 2 else 1) for pos, d in enumerate(reversed(digits[:-1]), start=1))
    if (10 - total % 10) % 10 != int(digits[-1]):
        raise ValueError("Некорректная контрольная цифра GTIN")
    return digits


def _text(value, limit=4000):
    s = "" if value is None else str(value).strip()
    if len(s) > limit:
        raise ValueError("Поле CSV превышает допустимую длину")
    return s or None


def _cost(value):
    s = str(value or "").strip().replace(",", ".")
    if not s or s == "~":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _open_csv(source):
    if hasattr(source, "read"):
        raw = source.read()
        if isinstance(raw, str):
            return io.StringIO(raw), None
        return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline=""), None
    path = str(source)
    if path.startswith(("http://", "https://")):
        with urllib.request.urlopen(path, timeout=int(os.getenv("MDLP_IMPORT_TIMEOUT", "180"))) as response:
            raw = response.read()
        return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline=""), path
    return open(path, "r", encoding="utf-8-sig", newline=""), os.path.basename(path)


def import_csv(source, db_path=None, source_updated_at=None):
    db_path = db_path or REFERENCE_DB
    init_reference_db(db_path)
    stream, source_name = _open_csv(source)
    imported_at = datetime.now(timezone.utc).isoformat()
    source_file = source_name or "memory.csv"
    try:
        reader = csv.DictReader(stream)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError("Неожиданный заголовок MDLP CSV")

        rows = []
        seen = set()
        for line_no, raw in enumerate(reader, start=2):
            if None in raw:
                raise ValueError(f"Строка {line_no}: лишние CSV-поля")
            gtin = _normalise_gtin(raw.get("gtin"))
            if gtin in seen:
                raise ValueError(f"Строка {line_no}: повторный GTIN {gtin}")
            seen.add(gtin)
            row = {key: _text(raw.get(key)) for key in EXPECTED_COLUMNS}
            row["gtin"] = gtin
            row["cost_limit"] = _cost(raw.get("cost_limit"))
            row["source_file"] = source_file
            row["source_updated_at"] = source_updated_at
            rows.append(row)

        if not rows:
            raise ValueError("MDLP CSV не содержит данных")

        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM mdlp_gtins")
            columns = EXPECTED_COLUMNS + ["source_file", "source_updated_at"]
            placeholders = ",".join("?" for _ in columns)
            sql = f"INSERT INTO mdlp_gtins ({','.join(columns)}) VALUES ({placeholders})"
            conn.executemany(sql, [tuple(row[c] for c in columns) for row in rows])
            conn.execute(
                """INSERT INTO mdlp_reference_meta(id, source_url, source_file, source_updated_at, row_count, imported_at)
                   VALUES(1, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET source_url=excluded.source_url,
                     source_file=excluded.source_file, source_updated_at=excluded.source_updated_at,
                     row_count=excluded.row_count, imported_at=excluded.imported_at""",
                (source if isinstance(source, str) and source.startswith(("http://", "https://")) else None,
                 source_file, source_updated_at, len(rows), imported_at),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return len(rows)
    finally:
        stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--db", default=REFERENCE_DB)
    parser.add_argument("--source-updated-at", default=None)
    args = parser.parse_args(argv)
    count = import_csv(args.source, args.db, args.source_updated_at)
    print(f"MDLP import: {count} rows -> {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
