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

class DrugReferenceAmbiguousError(ValueError):
    """GTIN связан более чем с одной действующей записью ГРЛС."""


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
        rows = conn.execute(
            """
            SELECT d.trade_name, d.inn, d.dosage_form, d.dosage_value,
                   d.manufacturer, d.holder, d.registration_date, d.expiry_date,
                   d.cancellation_date, d.production_stages,
                   d.pharmacotherapeutic_group, d.essential_drug,
                   d.contains_controlled_substances, d.orphan_status,
                   d.reg_number, g.package_desc
            FROM drug_gtins g
            JOIN drugs d ON d.id = g.drug_id
            WHERE g.gtin = %s AND d.status = 'действует'
            ORDER BY d.id
            LIMIT 2
            """,
            (gtin,),
        ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise DrugReferenceAmbiguousError(
            "GTIN связан с несколькими действующими регистрационными удостоверениями"
        )
    row = rows[0]
    return {
        "trade_name": row[0], "inn": row[1], "dosage_form": row[2],
        "dosage_value": row[3], "manufacturer": row[4], "holder": row[5],
        "registration_date": row[6].isoformat() if row[6] else None,
        "expiry_date": row[7].isoformat() if row[7] else None,
        "cancellation_date": row[8].isoformat() if row[8] else None,
        "production_stages": row[9],
        "pharmacotherapeutic_group": row[10],
        "essential_drug": row[11],
        "contains_controlled_substances": row[12],
        "orphan_status": row[13],
        "reg_number": row[14], "package_desc": row[15], "gtin": gtin,
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
    except DrugReferenceAmbiguousError:
        audit("drug_reference_ambiguous", "drug_gtins", None, {})
        return jsonify(
            error="Для этого GTIN найдено несколько действующих записей ГРЛС",
            code="ambiguous",
        ), 409
    except Exception as exc:
        print(f"[drugdb] lookup failed: {type(exc).__name__}", flush=True)
        return jsonify(error="Справочник лекарств временно недоступен", code="drugdb_unavailable"), 503

    if not result:
        audit("drug_reference_miss", "drug_gtins", None, {})
        return jsonify(error="Препарат для этого GTIN не найден", code="not_found"), 404

    audit("drug_reference_hit", "drug_gtins", None, {})
    return jsonify(result)
