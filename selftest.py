"""Офлайн-прогон всего сценария бота с поддельным Telegram API.

Запуск:  python selftest.py
Ничего никуда не отправляет — все запросы перехватываются.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

os.environ["WORK_DB"] = "selftest.db"
os.environ["BOT_TOKEN"] = "111:TEST"
if os.path.exists("selftest.db"):
    os.remove("selftest.db")

import bot as B  # noqa: E402
import db  # noqa: E402

WORKER = User(id=1001, is_bot=False, first_name="Влад", username="worker_test")
ADMIN = User(id=2002, is_bot=False, first_name="Макс", username="maximalusdt")
CHAT = Chat(id=1001, type="private")


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str]] = []
        self._mid = 100

    async def close(self) -> None:  # pragma: no cover
        pass

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        name = type(method).__name__
        text = getattr(method, "text", None) or ""
        chat_id = getattr(method, "chat_id", None)
        self.sent.append((f"{name}->{chat_id}" if chat_id else name, text))
        returning = method.__returning__
        if returning is Message or getattr(returning, "__name__", "") == "Message":
            self._mid += 1
            return Message(
                message_id=self._mid,
                date=dt.datetime.now(),
                chat=Chat(id=chat_id or CHAT.id, type="private"),
                text=text or None,
            )
        if returning is User:
            return User(id=999, is_bot=True, first_name="work", username="work_bot")
        return True


def msg(text: str, user: User = WORKER, mid: int = 1) -> Update:
    return Update(
        update_id=mid,
        message=Message(
            message_id=mid,
            date=dt.datetime.now(),
            chat=Chat(id=user.id, type="private"),
            from_user=user,
            text=text,
        ),
    )


def cb(data: str, user: User = WORKER, mid: int = 1) -> Update:
    return Update(
        update_id=mid + 500,
        callback_query=CallbackQuery(
            id=str(mid),
            from_user=user,
            chat_instance="ci",
            data=data,
            message=Message(
                message_id=mid,
                date=dt.datetime.now(),
                chat=Chat(id=user.id, type="private"),
                from_user=user,
                text="карточка",
            ),
        ),
    )


async def main() -> None:
    db.init()
    print(f"Бэкенд базы: {db.backend_name()}")
    prev_admin = db.get_setting("admin_id")  # чтобы не сбить боевую привязку

    session = FakeSession()
    bot = Bot("111:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    async def feed(update: Update, label: str) -> None:
        session.sent.clear()
        await B.dp.feed_update(bot, update)
        print(f"\n=== {label} " + "=" * (60 - len(label)))
        for method, text in session.sent:
            head = text.replace("\n", " ⏎ ")[:220]
            print(f"  [{method}] {head}")

    # админ активирует бота (чтобы бот запомнил его id)
    await feed(msg("/start", ADMIN, 1), "админ /start")
    assert db.get_setting("admin_id") == str(ADMIN.id), "админ не привязался"

    # смена
    await feed(msg("/start", WORKER, 2), "работник /start")
    await feed(cb("work:start", WORKER, 2), "кнопка «Начал работу»")
    row = db.active_session(WORKER.id)
    assert row and row["status"] == "running", "смена не запустилась"

    await feed(cb("work:pause", WORKER, 2), "пауза")
    assert db.active_session(WORKER.id)["status"] == "paused"
    elapsed_at_pause = db.elapsed_seconds(db.active_session(WORKER.id))
    await asyncio.sleep(1.2)
    assert db.elapsed_seconds(db.active_session(WORKER.id)) == elapsed_at_pause, (
        "таймер тикал на паузе!"
    )

    await feed(cb("work:resume", WORKER, 2), "пуск")
    assert db.active_session(WORKER.id)["status"] == "running"

    # подкручиваем начало смены на 13 часов назад, чтобы часы были реальные
    import time as _t
    sid = db.active_session(WORKER.id)["id"]
    db.execute(
        "UPDATE sessions SET started_at = ?, accumulated = ?, running_since = ? WHERE id = ?",
        (int(_t.time()) - 13 * 3600, 13 * 3600 - 5, int(_t.time()) - 5, sid),
    )

    await feed(cb("work:stop", WORKER, 2), "стоп работа")
    assert db.get_session(sid)["status"] == "finished"
    stop_to_admin = [t for m, t in session.sent if m.endswith(f"->{ADMIN.id}")]
    assert stop_to_admin, "админу не пришло уведомление о закрытии смены"
    print("=" * 70)
    print("АДМИНУ СРАЗУ ПОСЛЕ «СТОП»:")
    print(stop_to_admin[0])

    # анкета
    await feed(msg("300", WORKER, 3), "1) старт 300")
    await feed(msg("900", WORKER, 4), "2) конец 900")
    await feed(msg("50", WORKER, 5), "3) диспуты 50")
    await feed(cb("form:hasblocks", WORKER, 6), "5) были блоки")
    await feed(msg("ЛК 3, ЛК 7 — бан по верификации", WORKER, 7), "5) какие ЛК")
    await feed(msg("250", WORKER, 75), "5) сумма блока")
    await feed(msg("Долго висели выплаты, два ЛК ушли в бан", WORKER, 8), "6) сложности")
    await feed(msg("Поднять объём, догнать по диспутам", WORKER, 9), "7) планы")
    await feed(cb("form:send", WORKER, 10), "отправка заявки")

    to_admin = [t for m, t in session.sent if m.endswith(f"->{ADMIN.id}")]
    assert to_admin, "заявка не ушла админу!"
    print("\n" + "=" * 70)
    print("ЧТО ПОЛУЧИЛ АДМИН:\n")
    print(to_admin[0])

    rep = db.last_reports(1)[0]
    assert rep["profit"] == 550, rep["profit"]
    assert rep["percent"] == 15, rep["percent"]
    assert abs(rep["total"] - 82.5) < 0.01, rep["total"]

    # админ отмечает выплату
    await feed(cb(f"adm:paid:{rep['id']}", ADMIN, 11), "админ: выплачено")
    assert db.get_report(rep["id"])["paid"] == 1

    # статистика работника
    await feed(msg("/stats", WORKER, 12), "статистика работника")
    await feed(msg("/admin", ADMIN, 13), "админ-панель")

    # убираем за собой (важно, если прогон идёт по боевой базе Neon)
    for uid in (WORKER.id, ADMIN.id):
        db.execute("DELETE FROM reports WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
    if prev_admin:
        db.set_setting("admin_id", prev_admin)
    else:
        db.execute("DELETE FROM settings WHERE key = ?", ("admin_id",))

    print("\n✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ — тестовые записи из базы удалены")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
