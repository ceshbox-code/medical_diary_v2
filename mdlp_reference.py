"""Локальный справочник GTIN из официальной открытой выгрузки МДЛП.

Справочник хранится отдельно от медицинской БД пользователя. Он содержит только
публичные данные о лекарственных товарах и не содержит пользовательских данных.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

REFERENCE_DB = os.getenv("MDLP_REFERENCE_DB", "/reference/mdlp_reference.db")


def _connect(path=None, read_only=False):
    path = path or REFERENCE_DB
    if read_only:
        uri = "file:" + os.path.abspath(path) + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=2)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return sqlite3.connect(path, timeout=30)


def init_reference_db(path=None):
    conn = _connect(path)
    try:
        conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS mdlp_gtins (
          gtin TEXT PRIMARY KEY CHECK (length(gtin) = 14),
          prod_name TEXT,
          prod_norm_name TEXT,
          prod_desc TEXT,
          prod_sell_name TEXT,
          reg_id TEXT,
          reg_date TEXT,
          reg_holder TEXT,
          prod_d_name TEXT,
          prod_d_norm_name TEXT,
          mass_volume_name TEXT,
          prod_form_name TEXT,
          prod_form_norm_name TEXT,
          prod_pack_1_desc TEXT,
          prod_pack_1_2 TEXT,
          prod_pack_1_name TEXT,
          prod_pack_1_size TEXT,
          completeness TEXT,
          cost_limit REAL,
          glf_name TEXT,
          glf_country TEXT,
          gnvlp TEXT,
          narcotic TEXT,
          is_vzn_drug TEXT,
          inn TEXT,
          reg_status TEXT NOT NULL,
          source_file TEXT NOT NULL,
          source_updated_at TEXT,
          imported_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_mdlp_gtins_reg_id ON mdlp_gtins(reg_id);
        CREATE TABLE IF NOT EXISTS mdlp_reference_meta (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          source_url TEXT,
          source_file TEXT,
          source_updated_at TEXT,
          row_count INTEGER NOT NULL DEFAULT 0,
          imported_at TEXT NOT NULL
        );
        """)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def reference_connection(read_only=True):
    conn = _connect(read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def lookup_gtin(gtin):
    with reference_connection(read_only=True) as conn:
        row = conn.execute(
            """SELECT gtin, prod_sell_name, prod_name, prod_desc,
                      reg_id, reg_date, reg_holder, prod_d_name,
                      mass_volume_name, prod_form_name, prod_form_norm_name,
                      prod_pack_1_desc, prod_pack_1_2, prod_pack_1_name,
                      prod_pack_1_size, completeness, cost_limit, glf_name,
                      glf_country, gnvlp, narcotic, is_vzn_drug, inn, reg_status
               FROM mdlp_gtins WHERE gtin = ? AND lower(reg_status) = 'действующий' LIMIT 1""",
            (gtin,),
        ).fetchone()
    if not row:
        return None
    return {
        "gtin": row[0],
        "trade_name": row[1],
        # В CSV поле prod_name — МНН. Поле inn — ИНН организации,
        # поэтому inn намеренно НЕ используется как МНН.
        "inn": row[2],
        "description": row[3],
        "reg_number": row[4],
        "reg_date": row[5],
        "reg_holder": row[6],
        "dosage_value": row[7],
        "mass_volume_name": row[8],
        "dosage_form": row[9],
        "dosage_form_normalized": row[10],
        "package_desc": row[11],
        "package_count": _decimal_text(row[12]),
        "package_name": row[13],
        "package_size": _decimal_text(row[14]),
        "completeness": row[15],
        "cost_limit": row[16],
        "manufacturer": row[17],
        "manufacturer_country": row[18],
        "gnvlp": row[19],
        "narcotic": row[20],
        "is_vzn_drug": row[21],
        "reg_status": row[23],
        "organization_inn": row[22],
    }


def _decimal_text(value):
    if value is None:
        return None
    return str(value)
