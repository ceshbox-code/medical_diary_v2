"""Локальный справочник лекарств по официальной открытой выгрузке МДЛП.

Пользовательские медицинские данные не смешиваются со справочником: публичная
выгрузка хранится в отдельной SQLite БД. На запросе используется только GTIN.
"""
import re

from flask import Blueprint, jsonify, session

from mdlp_reference import lookup_gtin
from db import get_db\nfrom security import audit, login_required

drug_reference_bp = Blueprint("drug_reference", __name__)


class DrugReferenceUnavailableError(RuntimeError):
    """Локальный справочник временно недоступен."""


GTIN_LEN = 14


def _normalise_gtin(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(s) == 13:
        s = "0" + s
    if len(s) != GTIN_LEN:
        raise ValueError("GTIN должен содержать 14 цифр")
    total = sum(
        int(d) * (3 if pos % 2 else 1)
        for pos, d in enumerate(reversed(s[:-1]), start=1)
    )
    if (10 - total % 10) % 10 != int(s[-1]):
        raise ValueError("Некорректная контрольная цифра GTIN")
    return s


_PACKAGE_QTY_PATTERNS = (
    re.compile(
        r"(?<![\d.,])(?:№\s*)?(\d{1,6})\s*"
        r"(?:таблет(?:ка|ки|ок)|капсул(?:а|ы)|драже|"
        r"суппозитор(?:ий|ия|иев))\b",
        re.I,
    ),
    re.compile(
        r"(?<![\d.,])(?:№\s*)?(\d{1,6})\s*"
        r"(?:ампул(?:а|ы)|флакон(?:а|ов)?|штук|шт\.?)\b",
        re.I,
    ),
)


def _parse_package_quantity(package_desc):
    text = str(package_desc or "").strip()
    if not text:
        return None, None
    matches = []
    for pattern in _PACKAGE_QTY_PATTERNS:
        matches.extend(pattern.findall(text))
    values = {int(value) for value in matches}
    if len(values) != 1:
        return None, None
    value = next(iter(values))
    if 1 <= value <= 1000000:
        return value, "шт"
    return None, None


def lookup_drug_by_gtin(gtin, user_id=None):
    gtin = _normalise_gtin(gtin)

    if user_id is not None:
        override = get_db().execute(
            "SELECT name, mnn, dosage_form, manufacturer, reg_number, dose_value, "
            "dose_unit, intake_quantity, intake_unit, package_quantity, package_unit "
            "FROM medication_barcodes WHERE user_id = ? AND gtin = ? LIMIT 1",
            (user_id, gtin),
        ).fetchone()
        if override:
            return {
                "gtin": gtin,
                "trade_name": override["name"],
                "mnn": override["mnn"],
                "inn": override["mnn"],
                "organization_inn": None,
                "description": None,
                "dosage_form": override["dosage_form"],
                "dosage_form_normalized": override["dosage_form"],
                "dosage_value": None,
                "mass_volume_name": None,
                "manufacturer": override["manufacturer"],
                "manufacturer_country": None,
                "reg_number": override["reg_number"],
                "reg_date": None,
                "reg_holder": None,
                "reg_status": "пользовательская запись",
                "gnvlp": None,
                "narcotic": None,
                "is_vzn_drug": None,
                "package_desc": None,
                "package_quantity": override["package_quantity"],
                "package_unit": override["package_unit"],
                "intake_quantity": override["intake_quantity"],
                "intake_unit": override["intake_unit"],
                "dose_value_user": override["dose_value"],
                "dose_unit": override["dose_unit"],
                "source": "user_override",
            }

    try:
        result = lookup_gtin(gtin)
    except Exception as exc:
        raise DrugReferenceUnavailableError("Локальный справочник недоступен") from exc
    if not result:
        return None

    package_quantity, package_unit = _parse_package_quantity(result["package_desc"])

    # В текущем API поле inn исторически означает МНН. В исходном MDLP CSV
    # одноимённое поле inn — ИНН организации, поэтому оно не переносится сюда.
    return {
        "gtin": result["gtin"],
        "trade_name": result["trade_name"],
        "mnn": result["inn"],
        "inn": result["inn"],
        "organization_inn": None,
        "description": result["description"],
        "dosage_form": result["dosage_form"],
        "dosage_form_normalized": result["dosage_form_normalized"],
        "dosage_value": result["dosage_value"],
        "mass_volume_name": result["mass_volume_name"],
        "manufacturer": result["manufacturer"],
        "manufacturer_country": result["manufacturer_country"],
        "reg_number": result["reg_number"],
        "reg_date": result["reg_date"],
        "reg_holder": result["reg_holder"],
        "reg_status": result["reg_status"],
        "gnvlp": result["gnvlp"],
        "narcotic": result["narcotic"],
        "is_vzn_drug": result["is_vzn_drug"],
        "package_desc": result["package_desc"],
        "package_quantity": package_quantity,
        "package_unit": package_unit,
        "source": "mdlp_reference",
    }


@drug_reference_bp.get("/api/drug/by-gtin/<gtin>")
@login_required
def drug_by_gtin(gtin):
    try:
        gtin = _normalise_gtin(gtin)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    try:
        result = lookup_drug_by_gtin(gtin, user_id=session["user_id"])
    except DrugReferenceUnavailableError:
        print("[mdlp-reference] lookup failed", flush=True)
        return jsonify(
            error="Локальный справочник лекарств временно недоступен",
            code="drug_reference_unavailable",
        ), 503

    if not result:
        audit("drug_reference_miss", "mdlp_gtins", None, {})
        return jsonify(error="Препарат для этого GTIN не найден", code="not_found"), 404

    audit("drug_reference_hit", "mdlp_gtins", None, {})
    return jsonify(result)
