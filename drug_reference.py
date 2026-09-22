"""Локальный справочник лекарственных средств (PostgreSQL).

Приложение остаётся на Flask/SQLite; справочник вынесен в отдельную PostgreSQL БД.
Это позволяет загрузчику работать независимо от пользовательских медицинских данных.
"""
import os
from contextlib import contextmanager

from flask import Blueprint, jsonify, request

from security import login_required, audit

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

drug_reference_bp = Blueprint("drug_reference", __name__)
DSN = os.getenv("DRUG_DB_DSN", "").strip()
GTIN_LEN = 14


def _normalise_gtin(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(s) == 13:
        s = "0" + s
    if len(s) != GTIN_LEN:
        raise ValueError("GTIN должен содержать 14 цифр")
    total = sum(int(d) * (3 if pos % 2 else 1)
                for pos, d in enumerate(reversed(s[:-1]), start=1))
    if (10 - total % 10) % 10 != int(s[-1]):
        raise ValueError("Некорректная контрольная цифра GTIN")
    return s


@contextmanager
def _connection():
    if psycopg is None:
        raise RuntimeError("psycopg не установлен")
    if not DSN:
        raise RuntimeError("DRUG_DB_DSN не настроен")
    conn = psycopg.connect(DSN, connect_timeout=2)
    try:
        yield conn
    finally:
        conn.close()



def lookup_drug_by_gtin(gtin):
    gtin = _normalise_gtin(gtin)
    with _connection() as conn:
        row = conn.execute(
            """
            SELECT d.trade_name, d.inn, d.dosage_form, d.dosage_value,
                   d.manufacturer, d.holder, d.reg_number, g.package_desc
            FROM drug_gtins g
            JOIN drugs d ON d.id = g.drug_id
            WHERE g.gtin = %s AND d.status <> 'архив'
            ORDER BY d.id
            LIMIT 1
            """,
            (gtin,),
        ).fetchone()
    if not row:
        return None
    return {
        "trade_name": row[0], "inn": row[1], "dosage_form": row[2],
        "dosage_value": row[3], "manufacturer": row[4], "holder": row[5],
        "reg_number": row[6], "package_desc": row[7], "gtin": gtin,
    }

@drug_reference_bp.get("/api/drug/by-gtin/<gtin>")
@login_required
def drug_by_gtin(gtin):
    try:
        gtin = _normalise_gtin(gtin)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    try:
        result = lookup_drug_by_gtin(gtin)
    except Exception as exc:
        print(f"[drugdb] lookup failed: {type(exc).__name__}", flush=True)
        return jsonify(error="Справочник лекарств временно недоступен", code="drugdb_unavailable"), 503

    if not result:
        audit("drug_reference_miss", "drug_gtins", None, {"gtin": gtin})
        return jsonify(error="Препарат для этого GTIN не найден", code="not_found"), 404

    audit("drug_reference_hit", "drug_gtins", None, {"gtin": gtin, "reg_number": result["reg_number"]})
    return jsonify(result)
