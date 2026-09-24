"""Разбор лекарственного Data Matrix (GS1) для интеграции с Честным знаком.

Модуль намеренно не обращается к MDLP: он только валидирует и разбирает
идентификатор, полученный от сканера. Сетевой обмен с MDLP должен выполняться
на сервере отдельным клиентом.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ASCII 29 / GS1 Group Separator (FNC1 после серийного номера).
GS = "\x1d"
MAX_CODE_LENGTH = 4096
GTIN_AI = "01"
SERIAL_AI = "21"
EXPIRY_AI = "17"
BATCH_AI = "10"
PRODUCTION_AI = "11"


@dataclass(frozen=True)
class MarkingCode:
    raw: str
    gtin: str
    serial_number: str
    batch_number: str | None = None
    expiry_date: str | None = None
    production_date: str | None = None

    @property
    def sgtin(self) -> str:
        return self.gtin + self.serial_number


class MarkingCodeError(ValueError):
    """Ошибка структуры/контрольной цифры Data Matrix."""


def _clean(raw: str) -> str:
    if not isinstance(raw, str):
        raise MarkingCodeError("Код маркировки должен быть строкой")
    value = raw.strip()
    if not value or len(value) > MAX_CODE_LENGTH:
        raise MarkingCodeError("Некорректная длина кода маркировки")
    # Некоторые сканеры/камеры возвращают человекочитаемый AI-формат (01)... .
    value = value.replace("\\(", "(").replace("\\)", ")")
    # В человекочитаемом "(AI)значение(AI)значение" скобки заменяют
    # GS1-разделитель для переменной длины AI 10/21.
    matches = list(re.finditer(r"\((01|10|11|17|21)\)", value))
    if matches:
        chunks = []
        cursor = 0
        previous_ai = None
        for match in matches:
            # Скобки в человекочитаемой записи заменяют разделитель
            # переменной длины, поэтому GS должен стоять ПОСЛЕ значения
            # предыдущего AI 10/21 и перед следующим AI.
            chunks.append(value[cursor:match.start()])
            if previous_ai in (BATCH_AI, SERIAL_AI) and chunks:
                chunks.append(GS)
            chunks.append(match.group(1))
            cursor = match.end()
            previous_ai = match.group(1)
        chunks.append(value[cursor:])
        value = "".join(chunks)
    return value


def _gtin_check_digit(gtin13: str) -> str:
    total = 0
    for index, digit in enumerate(reversed(gtin13)):
        total += int(digit) * (3 if index % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def _validate_gtin(gtin: str) -> None:
    if len(gtin) != 14 or not gtin.isdigit():
        raise MarkingCodeError("GTIN должен содержать 14 цифр")
    if _gtin_check_digit(gtin[:13]) != gtin[13]:
        raise MarkingCodeError("Некорректная контрольная цифра GTIN")


def _parse_gs1_date(value: str, label: str) -> str:
    """GS1 YYMMDD -> ISO date."""
    if not re.fullmatch(r"\d{6}", value):
        raise MarkingCodeError(f"{label}: ожидается дата YYMMDD")
    yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:6])
    year = 2000 + yy if yy <= 49 else 1900 + yy
    try:
        from datetime import date
        return date(year, mm, dd).isoformat()
    except ValueError:
        raise MarkingCodeError(f"{label}: некорректная дата")


def parse_marking_code(raw: str) -> MarkingCode:
    value = _clean(raw)
    if not value.startswith(GTIN_AI):
        raise MarkingCodeError("Код не начинается с AI 01 (GTIN)")
    gtin = value[2:16]
    _validate_gtin(gtin)
    pos = 16
    serial = None
    batch = None
    expiry = None
    production = None

    while pos < len(value):
        ai = value[pos:pos + 2]
        pos += 2
        if ai == SERIAL_AI:
            end = value.find(GS, pos)
            if end < 0:
                serial = value[pos:pos + 13]
                pos += len(serial)
            else:
                serial = value[pos:end]
                pos = end + 1
        elif ai in (EXPIRY_AI, PRODUCTION_AI):
            if pos + 6 > len(value):
                raise MarkingCodeError(f"AI {ai}: неполная дата")
            date_value = value[pos:pos + 6]
            pos += 6
            if ai == EXPIRY_AI:
                expiry = _parse_gs1_date(date_value, "Срок годности")
            else:
                production = _parse_gs1_date(date_value, "Дата производства")
        elif ai == BATCH_AI:
            end = value.find(GS, pos)
            if end < 0:
                batch = value[pos:]
                pos = len(value)
            else:
                batch = value[pos:end]
                pos = end + 1
            if not batch or len(batch) > 20 or not re.fullmatch(r"[!-~]+", batch):
                raise MarkingCodeError("AI 10: некорректный номер серии")
        else:
            break

    if serial is None:
        raise MarkingCodeError("В коде не найден серийный номер AI 21")
    if not serial or len(serial) != 13 or not re.fullmatch(r"[!-~]+", serial):
        raise MarkingCodeError("Некорректный серийный номер")

    return MarkingCode(
        raw=value,
        gtin=gtin,
        serial_number=serial,
        batch_number=batch,
        expiry_date=expiry,
        production_date=production,
    )
