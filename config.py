"""Конфигурация бота WORK."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env() -> None:
    """Простейший .env-лоадер (без внешних зависимостей)."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

# --- Telegram -------------------------------------------------------------
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

# Юзернейм админа (для кнопки «написать админу» и для авто-привязки ID).
ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "maximalusdt").lstrip("@")

# Числовой ID админа. Если пусто — бот сам запомнит его, когда админ
# (по юзернейму выше) первый раз напишет /start.
_admin_id_raw = os.environ.get("ADMIN_ID", "").strip()
ADMIN_ID: int | None = int(_admin_id_raw) if _admin_id_raw.lstrip("-").isdigit() else None

# --- Ставки ---------------------------------------------------------------
# Проценты от профита: (верхняя граница профита, процент).
# Профит < 300  -> 12%
# 300 <= p < 500 -> 13%
# 500 <= p < 800 -> 15%
# p >= 800       -> 16%
PERCENT_TIERS: tuple[tuple[float | None, float], ...] = (
    (300.0, 12.0),
    (500.0, 13.0),
    (800.0, 15.0),
    (None, 16.0),
)

# Фикс за час при наличии блоков.
BLOCK_FIX_PER_HOUR: float = 3.5

# Как считать выплату, если были блоки:
#   "max" — работник получает наибольшее из (процент, фикс)  [по умолчанию]
#   "fix" — при блоках всегда только фикс
BLOCK_PAY_MODE: str = os.environ.get("BLOCK_PAY_MODE", "max").lower()

# --- Прочее ---------------------------------------------------------------
# Если задан DATABASE_URL (Neon/Postgres) — данные живут там и переживают
# любые рестарты хостинга. Иначе локальный SQLite-файл.
DATABASE_URL: str = os.environ.get("DATABASE_URL", "").strip()
DB_PATH: Path = BASE_DIR / os.environ.get("WORK_DB", "work.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
TIMEZONE_OFFSET: int = int(os.environ.get("TZ_OFFSET", "3"))  # МСК по умолчанию
LIVE_UPDATE_SECONDS: int = 60  # как часто обновлять «живой» таймер
