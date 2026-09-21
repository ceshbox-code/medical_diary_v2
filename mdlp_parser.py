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


@dataclass(frozen=True)
class MarkingCode:
    raw: str
    gtin: str
    serial_number: str

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
    value = re.sub(r"\((?:01|21)\)", lambda m: m.group(0)[1:-1], value)
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


def parse_marking_code(raw: str) -> MarkingCode:
    value = _clean(raw)

    # Стандартный вариант для лекарств: AI 01 + GTIN(14), затем AI 21 +
    # серийный номер. После серийного номера сканер обычно возвращает GS/FNC1,
    # после которого могут следовать криптографические данные.
    if value.startswith(GTIN_AI):
        gtin = value[2:16]
        _validate_gtin(gtin)
        rest = value[16:]
        if not rest.startswith(SERIAL_AI):
            raise MarkingCodeError("В коде не найден серийный номер AI 21")
        serial_and_tail = rest[2:]
    else:
        # Поддерживаем только явно размеченный альтернативный ввод вида
        # "01...21..." после удаления скобок. Иные форматы не угадываем.
        raise MarkingCodeError("Код не начинается с AI 01 (GTIN)")

    serial = serial_and_tail.split(GS, 1)[0]
    if not serial:
        raise MarkingCodeError("Пустой серийный номер")
    if len(serial) > 30 or not re.fullmatch(r"[!-~]+", serial):
        raise MarkingCodeError("Некорректный серийный номер")
    return MarkingCode(raw=value, gtin=gtin, serial_number=serial)
