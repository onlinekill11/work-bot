"""WORK — телеграм-бот учёта смены и заявок на вывод."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramConflictError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message

import db
import ui
from calc import calculate, money
from config import ADMIN_ID, ADMIN_USERNAME, BOT_TOKEN, LIVE_UPDATE_SECONDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("work")

dp = Dispatcher(storage=MemoryStorage())


class Form(StatesGroup):
    start_balance = State()
    end_balance = State()
    disputes = State()
    hours = State()
    blocks = State()
    blocks_text = State()
    problems = State()
    plans = State()
    confirm = State()


# --- helpers --------------------------------------------------------------
def admin_id() -> int | None:
    if ADMIN_ID:
        return ADMIN_ID
    saved = db.get_setting("admin_id")
    return int(saved) if saved and saved.lstrip("-").isdigit() else None


def is_admin(user_id: int, username: str | None) -> bool:
    if username and username.lower() == ADMIN_USERNAME.lower():
        return True
    return admin_id() == user_id


_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def parse_money(text: str) -> float | None:
    cleaned = text.replace(" ", "").replace(" ", "")
    match = _NUM_RE.search(cleaned)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


_RANGE_RE = re.compile(r"(\d{1,2})[:.](\d{2})\s*[-–—до]+\s*(\d{1,2})[:.](\d{2})")


def parse_shift(text: str) -> tuple[float, str] | None:
    """«16:00 - 05:00» -> (13.0, '16:00 — 05:00 (13 ч)'); «13» -> (13.0, '13 ч')."""
    m = _RANGE_RE.search(text)
    if m:
        h1, m1, h2, m2 = (int(g) for g in m.groups())
        if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
            return None
        minutes = (h2 * 60 + m2) - (h1 * 60 + m1)
        if minutes <= 0:
            minutes += 24 * 60
        hours = minutes / 60
        label = f"{h1:02d}:{m1:02d} — {h2:02d}:{m2:02d} ({ui.fmt_hours(minutes * 60)})"
        return hours, label
    value = parse_money(text)
    if value is None or value <= 0 or value > 24:
        return None
    return value, ui.fmt_hours(int(value * 3600))


async def show_state_card(bot: Bot, chat_id: int, user_id: int, name: str) -> None:
    """Показывает актуальную карточку смены (новым сообщением)."""
    row = db.active_session(user_id)
    if not row:
        await bot.send_message(chat_id, ui.idle_card(name), reply_markup=ui.kb_idle())
        return
    elapsed = db.elapsed_seconds(row)
    text = ui.session_card(
        status=row["status"],
        started_at=row["started_at"],
        elapsed=elapsed,
        pauses=row["pauses"],
    )
    kb = ui.kb_running() if row["status"] == "running" else ui.kb_paused()
    msg = await bot.send_message(chat_id, text, reply_markup=kb)
    db.set_session_msg(row["id"], msg.message_id)


async def refresh_card(bot: Bot, user_id: int) -> None:
    """Обновляет уже отправленную карточку смены на месте."""
    row = db.active_session(user_id)
    if not row or not row["msg_id"]:
        return
    text = ui.session_card(
        status=row["status"],
        started_at=row["started_at"],
        elapsed=db.elapsed_seconds(row),
        pauses=row["pauses"],
    )
    kb = ui.kb_running() if row["status"] == "running" else ui.kb_paused()
    with contextlib.suppress(TelegramBadRequest):
        await bot.edit_message_text(
            text, chat_id=user_id, message_id=row["msg_id"], reply_markup=kb
        )


# --- команды --------------------------------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = message.from_user
    db.upsert_user(user.id, user.username, user.full_name)
    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        db.set_setting("admin_id", str(user.id))
        log.info("Админ привязан: @%s (%s)", user.username, user.id)
    await message.answer(ui.welcome(user.first_name or "работник"))
    await show_state_card(bot, message.chat.id, user.id, user.first_name or "работник")


@dp.message(Command("work", "smena", "menu"))
async def cmd_work(message: Message, bot: Bot) -> None:
    db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await show_state_card(
        bot, message.chat.id, message.from_user.id, message.from_user.first_name or "работник"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(ui.help_text(), reply_markup=ui.kb_contact_admin())


@dp.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    await message.answer(stats_text(message.from_user.id))


def stats_text(user_id: int) -> str:
    s = db.user_stats(user_id)
    rows = db.user_reports(user_id, limit=5)
    lines = [
        "<b>📊 МОЯ СТАТИСТИКА</b>",
        ui.LINE,
        f"Смен сдано: <b>{s['days']}</b>",
        f"Часов отработано: <b>{s['hours']:.1f}</b>",
        f"Профит суммарно: <b>{money(s['profit'])}</b>",
        f"Заработано: <b>{money(s['total'])}</b>",
    ]
    if rows:
        lines += [ui.LINE, "<b>Последние смены:</b>"]
        for r in rows:
            mark = "✅" if r["paid"] else "🕓"
            lines.append(
                f"{mark} {ui.day(r['created_at'])} — профит {money(r['profit'])}, "
                f"выплата {money(r['total'])}"
            )
    return "\n".join(lines)


@dp.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    user = message.from_user
    if not is_admin(user.id, user.username):
        return
    db.set_setting("admin_id", str(user.id))
    live = db.all_live_sessions()
    lines = ["<b>🛠 АДМИН-ПАНЕЛЬ</b>", ui.LINE]
    if live:
        lines.append("<b>Сейчас на смене:</b>")
        for row in live:
            u = db.get_user(row["user_id"])
            who = ui.user_tag(
                u["username"] if u else None,
                u["full_name"] if u else "?",
                row["user_id"],
            )
            mark = "🟢" if row["status"] == "running" else "⏸"
            lines.append(
                f"{mark} {who} — {ui.fmt_hms(db.elapsed_seconds(row))} "
                f"(с {ui.clock(row['started_at'])})"
            )
    else:
        lines.append("<i>Сейчас никто не на смене.</i>")

    reports = db.last_reports(10)
    lines += [ui.LINE, "<b>Последние заявки:</b>"]
    if reports:
        for r in reports:
            mark = "✅" if r["paid"] else "🕓"
            who = ui.user_tag(r["username"], r["full_name"] or "?", r["user_id"])
            lines.append(
                f"{mark} №{r['id']} {who} — профит {money(r['profit'])}, "
                f"к выплате <b>{money(r['total'])}</b> ({ui.day(r['created_at'])})"
            )
    else:
        lines.append("<i>Заявок пока нет.</i>")
    await message.answer("\n".join(lines))


# --- таймер ---------------------------------------------------------------
@dp.callback_query(F.data == "work:start")
async def cb_start(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = call.from_user
    db.upsert_user(user.id, user.username, user.full_name)
    if db.active_session(user.id):
        await call.answer("Смена уже идёт", show_alert=True)
        return
    session_id = db.start_session(user.id)
    db.set_session_msg(session_id, call.message.message_id)
    row = db.get_session(session_id)
    await call.message.edit_text(
        ui.session_card(status="running", started_at=row["started_at"], elapsed=0, pauses=0),
        reply_markup=ui.kb_running(),
    )
    await call.answer("Смена началась 🟢")


@dp.callback_query(F.data == "work:pause")
async def cb_pause(call: CallbackQuery, bot: Bot) -> None:
    row = db.active_session(call.from_user.id)
    if not row:
        await call.answer("Активной смены нет", show_alert=True)
        return
    if row["status"] == "paused":
        await call.answer("Уже на паузе")
        return
    db.pause_session(row["id"])
    db.set_session_msg(row["id"], call.message.message_id)
    await refresh_card(bot, call.from_user.id)
    await call.answer("Пауза ⏸")


@dp.callback_query(F.data == "work:resume")
async def cb_resume(call: CallbackQuery, bot: Bot) -> None:
    row = db.active_session(call.from_user.id)
    if not row:
        await call.answer("Активной смены нет", show_alert=True)
        return
    db.resume_session(row["id"])
    db.set_session_msg(row["id"], call.message.message_id)
    await refresh_card(bot, call.from_user.id)
    await call.answer("Поехали ▶️")


@dp.callback_query(F.data == "work:refresh")
async def cb_refresh(call: CallbackQuery, bot: Bot) -> None:
    row = db.active_session(call.from_user.id)
    if row:
        db.set_session_msg(row["id"], call.message.message_id)
    await refresh_card(bot, call.from_user.id)
    await call.answer("Обновил")


@dp.callback_query(F.data == "work:stop")
async def cb_stop(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    user = call.from_user
    row = db.active_session(user.id)
    if not row:
        await call.answer("Активной смены нет", show_alert=True)
        return
    db.upsert_user(user.id, user.username, user.full_name)
    elapsed = db.finish_session(row["id"])
    finished = db.get_session(row["id"])

    # админу — сразу, не дожидаясь заполнения анкеты
    target = admin_id()
    if target:
        with contextlib.suppress(Exception):
            await bot.send_message(
                target,
                ui.admin_shift_closed(
                    full_name=user.full_name,
                    username=user.username,
                    user_id=user.id,
                    started_at=finished["started_at"],
                    finished_at=finished["finished_at"],
                    elapsed=elapsed,
                    pauses=finished["pauses"],
                ),
            )
    else:
        log.warning("ADMIN_ID не задан — уведомление о смене не ушло")

    shift_str = (
        f"{ui.clock(finished['started_at'])} — {ui.clock(finished['finished_at'])} "
        f"({ui.fmt_hours(elapsed)})"
    )
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            ui.finished_card(
                started_at=finished["started_at"],
                finished_at=finished["finished_at"],
                elapsed=elapsed,
            )
        )
    await state.set_state(Form.start_balance)
    await state.update_data(
        session_id=row["id"],
        hours=elapsed / 3600,
        shift_str=shift_str,
    )
    await call.message.answer(ui.q_start())
    await call.answer("Смена закрыта 🏁")


@dp.callback_query(F.data == "work:stats")
async def cb_stats(call: CallbackQuery) -> None:
    await call.message.answer(stats_text(call.from_user.id))
    await call.answer()


@dp.callback_query(F.data == "work:help")
async def cb_help(call: CallbackQuery) -> None:
    await call.message.answer(ui.help_text(), reply_markup=ui.kb_contact_admin())
    await call.answer()


# --- анкета ---------------------------------------------------------------
@dp.message(Command("report", "otchet"))
async def cmd_report(message: Message, state: FSMContext) -> None:
    if db.active_session(message.from_user.id):
        await message.answer(
            "Сначала заверши смену кнопкой <b>«Стоп работа»</b> — "
            "тогда часы подставятся сами."
        )
        return
    await state.clear()
    await state.set_state(Form.start_balance)
    await message.answer(ui.q_start())


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await message.answer("Заполнение отменено.")
    await show_state_card(
        bot, message.chat.id, message.from_user.id, message.from_user.first_name or "работник"
    )


@dp.message(Form.start_balance)
async def f_start(message: Message, state: FSMContext) -> None:
    value = parse_money(message.text or "")
    if value is None:
        await message.answer("Нужно число. Например: <code>300</code>")
        return
    await state.update_data(start=value)
    await state.set_state(Form.end_balance)
    await message.answer(ui.q_end(value))


@dp.message(Form.end_balance)
async def f_end(message: Message, state: FSMContext) -> None:
    value = parse_money(message.text or "")
    if value is None:
        await message.answer("Нужно число. Например: <code>900</code>")
        return
    data = await state.update_data(end=value)
    await state.set_state(Form.disputes)
    await message.answer(ui.q_disputes(data["start"], value), reply_markup=ui.kb_no_disputes())


async def _after_disputes(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if "hours" in data:
        await state.set_state(Form.blocks)
        await message.answer(
            ui.q_blocks(data.get("shift_str")), reply_markup=ui.kb_blocks()
        )
    else:
        await state.set_state(Form.hours)
        await message.answer(ui.q_hours())


@dp.message(Form.disputes)
async def f_disputes(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    if text in {"нет", "не было", "0", "-", "нету"}:
        value = 0.0
    else:
        parsed = parse_money(text)
        if parsed is None:
            await message.answer(
                "Нужна сумма диспутов в баксах. Например: <code>50</code>\n"
                "Если диспутов не было — жми кнопку или напиши <code>0</code>."
            )
            return
        value = abs(parsed)
    await state.update_data(disputes=value)
    await _after_disputes(message, state)


@dp.callback_query(F.data == "form:nodisputes", Form.disputes)
async def cb_no_disputes(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(disputes=0.0)
    await call.answer("Диспутов нет")
    await _after_disputes(call.message, state)


@dp.message(Form.hours)
async def f_hours(message: Message, state: FSMContext) -> None:
    parsed = parse_shift(message.text or "")
    if not parsed:
        await message.answer(
            "Не понял время. Напиши так: <code>16:00 - 05:00</code> или <code>13</code>"
        )
        return
    hours, label = parsed
    await state.update_data(hours=hours, shift_str=label)
    await state.set_state(Form.blocks)
    await message.answer(ui.q_blocks(), reply_markup=ui.kb_blocks())


@dp.callback_query(F.data == "form:noblocks", Form.blocks)
async def cb_no_blocks(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(blocks_text=None)
    await state.set_state(Form.problems)
    await call.answer("Блоков нет")
    await call.message.answer(ui.q_problems(), reply_markup=ui.kb_skip())


@dp.callback_query(F.data == "form:hasblocks", Form.blocks)
async def cb_has_blocks(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.blocks_text)
    await call.answer()
    await call.message.answer(ui.q_blocks_text())


@dp.message(Form.blocks)
async def f_blocks_free(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() in {"нет", "не было", "-", "0", "нету"}:
        await state.update_data(blocks_text=None)
        await state.set_state(Form.problems)
        await message.answer(ui.q_problems(), reply_markup=ui.kb_skip())
        return
    await state.update_data(blocks_text=text)
    await state.set_state(Form.problems)
    await message.answer(ui.q_problems(), reply_markup=ui.kb_skip())


@dp.message(Form.blocks_text)
async def f_blocks_text(message: Message, state: FSMContext) -> None:
    await state.update_data(blocks_text=(message.text or "").strip())
    await state.set_state(Form.problems)
    await message.answer(ui.q_problems(), reply_markup=ui.kb_skip())


@dp.callback_query(F.data == "form:skip", Form.problems)
async def cb_skip_problems(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(problems="—")
    await state.set_state(Form.plans)
    await call.answer()
    await call.message.answer(ui.q_plans())


@dp.message(Form.problems)
async def f_problems(message: Message, state: FSMContext) -> None:
    await state.update_data(problems=(message.text or "").strip())
    await state.set_state(Form.plans)
    await message.answer(ui.q_plans())


@dp.message(Form.plans)
async def f_plans(message: Message, state: FSMContext) -> None:
    data = await state.update_data(plans=(message.text or "").strip())
    await state.set_state(Form.confirm)
    await message.answer(ui.confirm_card(data), reply_markup=ui.kb_confirm())


@dp.callback_query(F.data == "form:restart", Form.confirm)
async def cb_restart(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    keep = {k: data[k] for k in ("session_id", "hours", "shift_str") if k in data}
    await state.set_data(keep)
    await state.set_state(Form.start_balance)
    await call.answer("Начинаем заново")
    await call.message.answer(ui.q_start())


@dp.callback_query(F.data == "form:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await call.answer("Отменено")
    await call.message.answer("Заявка отменена.")
    await show_state_card(
        bot, call.message.chat.id, call.from_user.id, call.from_user.first_name or "работник"
    )


@dp.callback_query(F.data == "form:send", Form.confirm)
async def cb_send(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    user = call.from_user
    db.upsert_user(user.id, user.username, user.full_name)

    payout = calculate(
        start=data["start"],
        end=data["end"],
        disputes=data.get("disputes", 0.0),
        hours=data["hours"],
        has_blocks=bool(data.get("blocks_text")),
    )

    report_id = db.save_report(
        {
            "user_id": user.id,
            "session_id": data.get("session_id"),
            "created_at": int(time.time()),
            "start_bal": payout.start,
            "end_bal": payout.end,
            "disputes": payout.disputes,
            "profit": payout.profit,
            "percent": payout.percent,
            "percent_pay": payout.percent_pay,
            "hours": payout.hours,
            "has_blocks": int(payout.has_blocks),
            "blocks_text": data.get("blocks_text"),
            "fix_pay": payout.fix_pay,
            "total": payout.total,
            "difficulties": data.get("problems"),
            "plans": data.get("plans"),
        }
    )

    text = ui.admin_report(
        report_id=report_id,
        who=ui.user_tag(user.username, user.full_name, user.id),
        date_str=ui.day(int(time.time())),
        p=payout,
        shift_str=data["shift_str"],
        blocks_text=data.get("blocks_text"),
        problems=data.get("problems") or "",
        plans=data.get("plans") or "",
    )

    target = admin_id()
    delivered = False
    if target:
        try:
            await bot.send_message(
                target, text, reply_markup=ui.kb_admin_report(report_id, user.id)
            )
            delivered = True
        except Exception as exc:  # noqa: BLE001 - логируем и сообщаем работнику
            log.error("Не смог отправить заявку админу: %s", exc)
    else:
        log.warning("ADMIN_ID не задан — заявка №%s не доставлена", report_id)

    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Заявка отправлена")
    await call.message.answer(ui.payout_card(payout, data["shift_str"]))
    if not delivered:
        await call.message.answer(
            "⚠️ Заявка сохранена, но админ ещё не активировал бота — "
            f"перешли ему номер заявки №{report_id}.",
            reply_markup=ui.kb_contact_admin(),
        )


@dp.callback_query(F.data.startswith("adm:paid:"))
async def cb_paid(call: CallbackQuery, bot: Bot) -> None:
    if not is_admin(call.from_user.id, call.from_user.username):
        await call.answer("Только для админа", show_alert=True)
        return
    report_id = int(call.data.split(":")[2])
    row = db.get_report(report_id)
    if not row:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    db.mark_paid(report_id)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            call.message.html_text + f"\n\n✅ <b>ВЫПЛАЧЕНО</b> {money(row['total'])}"
        )
    with contextlib.suppress(Exception):
        await bot.send_message(
            row["user_id"],
            f"💸 Заявка №{report_id} выплачена: <b>{money(row['total'])}</b>",
        )
    await call.answer("Отмечено")


@dp.callback_query()
async def cb_stale(call: CallbackQuery) -> None:
    await call.answer("Кнопка устарела — открой меню командой /work", show_alert=True)


# --- фоновое обновление таймеров -----------------------------------------
async def live_ticker(bot: Bot) -> None:
    while True:
        await asyncio.sleep(LIVE_UPDATE_SECONDS)
        for row in db.all_live_sessions():
            if row["status"] != "running" or not row["msg_id"]:
                continue
            with contextlib.suppress(Exception):
                await bot.edit_message_text(
                    ui.session_card(
                        status=row["status"],
                        started_at=row["started_at"],
                        elapsed=db.elapsed_seconds(row),
                        pauses=row["pauses"],
                    ),
                    chat_id=row["user_id"],
                    message_id=row["msg_id"],
                    reply_markup=ui.kb_running(),
                )


# --- обвязка для хостинга -------------------------------------------------
async def health_server() -> None:
    """HTTP-заглушка: Render/HF/Railway требуют открытый порт, иначе гасят сервис."""
    port = os.environ.get("PORT")
    if not port:
        return
    from aiohttp import web

    started = int(time.time())

    async def status(_request: "web.Request") -> "web.Response":
        live = db.all_live_sessions()
        return web.json_response(
            {
                "ok": True,
                "bot": "work",
                "uptime_sec": int(time.time()) - started,
                "on_shift": len(live),
            }
        )

    app = web.Application()
    app.router.add_get("/", status)
    app.router.add_get("/health", status)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    log.info("HTTP health-сервер поднят на порту %s", port)


async def keepalive() -> None:
    """Самопинг для хостингов, которые усыпляют сервис без трафика."""
    url = os.environ.get("KEEPALIVE_URL")
    if not url:
        return
    import aiohttp

    while True:
        await asyncio.sleep(600)
        with contextlib.suppress(Exception):
            async with aiohttp.ClientSession() as session:
                await session.get(url, timeout=aiohttp.ClientTimeout(total=30))
                log.info("keepalive ping -> %s", url)


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "Не задан BOT_TOKEN. Создай файл .env рядом с bot.py и впиши:\n"
            "BOT_TOKEN=123456:AA...\n"
        )
    db.init()
    log.info("База: %s", db.backend_name())
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands(
        [
            BotCommand(command="work", description="💼 Меню смены"),
            BotCommand(command="report", description="📝 Заполнить заявку"),
            BotCommand(command="stats", description="📊 Моя статистика"),
            BotCommand(command="help", description="❓ Как это работает"),
            BotCommand(command="cancel", description="❌ Отменить заполнение"),
        ]
    )
    me = await bot.get_me()
    log.info("Бот запущен: @%s", me.username)
    await health_server()
    asyncio.create_task(live_ticker(bot))
    asyncio.create_task(keepalive())
    try:
        await dp.start_polling(bot)
    except TelegramConflictError:
        log.error(
            "Конфликт: этот бот уже запущен где-то ещё (локально или на хостинге). "
            "Держи включённой только ОДНУ копию."
        )
        raise


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
