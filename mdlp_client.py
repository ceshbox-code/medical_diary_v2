"""Минимальный серверный клиент MDLP для тестового контура.

По умолчанию работает только с sandbox. Секреты читаются из окружения.
Для резидента в production/sandbox получение session token требует подписи
ГОСТ-сертификатом; приложение не пытается реализовать криптографию само.
Можно передать уже полученный динамический token через MDLP_TOKEN.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class MDLPError(RuntimeError):
    def __init__(self, message: str, kind: str = "unavailable", status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass
class MDLPConfig:
    enabled: bool
    base_url: str
    token: str | None
    timeout: float
    max_response_bytes: int

    @classmethod
    def from_env(cls) -> "MDLPConfig":
        mode = os.getenv("MDLP_MODE", "sandbox").strip().lower()
        if mode not in {"sandbox", "production"}:
            raise MDLPError("MDLP_MODE должен быть sandbox или production", "config")
        default_url = "https://api.sb.mdlp.crpt.ru" if mode == "sandbox" else "https://api.mdlp.crpt.ru"
        base_url = os.getenv("MDLP_BASE_URL", default_url).rstrip("/")
        if not (base_url.startswith("https://api.sb.mdlp.crpt.ru") if mode == "sandbox"
                else base_url.startswith("https://api.mdlp.crpt.ru")):
            raise MDLPError("MDLP_BASE_URL не соответствует MDLP_MODE", "config")
        return cls(
            enabled=os.getenv("MDLP_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            base_url=base_url,
            token=os.getenv("MDLP_TOKEN") or None,
            timeout=float(os.getenv("MDLP_TIMEOUT", "15")),
            max_response_bytes=int(os.getenv("MDLP_MAX_RESPONSE_BYTES", "1048576")),
        )


class MDLPClient:
    def __init__(self, config: MDLPConfig | None = None):
        self.config = config or MDLPConfig.from_env()

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise MDLPError("Интеграция MDLP отключена", "disabled")
        if not self.config.token:
            raise MDLPError(
                "Не задан MDLP_TOKEN. Для резидента динамический token должен быть "
                "получен через штатную процедуру MDLP с ГОСТ-подписью.",
                "auth",
            )

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.config.base_url + "/api/v1/" + path.lstrip("/"),
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "token " + self.config.token,
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as response:
                raw = response.read(self.config.max_response_bytes + 1)
                if len(raw) > self.config.max_response_bytes:
                    raise MDLPError("Ответ MDLP превышает допустимый размер", "protocol")
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096)
            detail = raw.decode("utf-8", errors="replace")
            if exc.code in (401, 403):
                kind = "auth"
            elif exc.code == 429:
                kind = "rate_limit"
            elif 500 <= exc.code < 600:
                kind = "unavailable"
            else:
                kind = "rejected"
            raise MDLPError(f"MDLP HTTP {exc.code}", kind, exc.code) from exc
        except urllib.error.URLError as exc:
            raise MDLPError("MDLP недоступен: " + str(exc.reason), "unavailable") from exc
        except TimeoutError as exc:
            raise MDLPError("Истек таймаут MDLP", "timeout") from exc
        except (ValueError, UnicodeError) as exc:
            raise MDLPError("MDLP вернул некорректный JSON", "protocol") from exc

    def find_public_sgtin(self, sgtin: str) -> dict[str, Any] | None:
        """8.3.3: поиск по общедоступному реестру КИЗ по списку значений."""
        result = self._request("reestr/sgtin/public/sgtins-by-list", {"filter": {"sgtins": [sgtin]}})
        entries = result.get("entries")
        if not isinstance(entries, list):
            raise MDLPError("Неожиданный формат ответа 8.3.3: нет entries", "protocol")
        for entry in entries:
            if isinstance(entry, dict) and entry.get("sgtin") == sgtin:
                return entry
        return None
