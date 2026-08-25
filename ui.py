"""Вся визуальная часть: тексты, карточки, клавиатуры."""
from __future__ import annotations

import datetime as dt

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from calc import Payout, money
from config import ADMIN_USERNAME, TIMEZONE_OFFSET

LINE = "━━━━━━━━━━━━━━━━━━━━"
STEPS_TOTAL = 7


# --- форматирование -------------------------------------------------------
def fmt_hms(seconds: int) -> str:
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_hours(seconds: int) -> str:
    h, rest = divmod(max(0, int(seconds)), 3600)
    m = rest // 60
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    return f"{m} мин"


def local_dt(ts: int | None) -> dt.datetime | None:
    if not ts:
        return None
    return dt.datetime.utcfromtimestamp(ts) + dt.timedelta(hours=TIMEZONE_OFFSET)


def clock(ts: int | None) -> str:
    d = local_dt(ts)
    return d.strftime("%H:%M") if d else "—"


def day(ts: int | None) -> str:
    d = local_dt(ts)
    return d.strftime("%d.%m.%Y") if d else "—"


def progress(step: int, total: int = STEPS_TOTAL) -> str:
    filled = "▰" * step
    empty = "▱" * (total - step)
    return f"Шаг {step} из {total}   {filled}{empty}"


def user_tag(username: str | None, full_name: str, user_id: int) -> str:
    if username:
        return f"@{username}"
    return f"{full_name} (id {user_id})"


# --- экраны ---------------------------------------------------------------
def welcome(name: str) -> str:
    return (
        "<b>💼  W O R K</b>\n"
        f"{LINE}\n"
        f"Привет, <b>{name}</b>!\n\n"
        "Здесь ты ведёшь свою смену:\n"
        "▸ <b>Начал работу</b> — стартует таймер\n"
        "▸ <b>Пауза / Пуск</b> — перерыв без потери времени\n"
        "▸ <b>Стоп работа</b> — итог смены и отчёт\n\n"
        "После смены бот сам посчитает профит, ставку "
        "и твой заработок за день.\n"
        f"{LINE}\n"
        "<i>Готов? Жми кнопку ниже 👇</i>"
    )


def idle_card(name: str) -> str:
    return (
        "<b>💼  W O R K</b>\n"
        f"{LINE}\n"
        "⚪️ <b>Смена не начата</b>\n\n"
        f"Работник: <b>{name}</b>\n"
        "Таймер: <code>00:00:00</code>\n"
        f"{LINE}\n"
        "<i>Нажми «Начал работу», чтобы запустить смену.</i>"
    )


def session_card(*, status: str, started_at: int, elapsed: int, pauses: int) -> str:
    if status == "running":
        head = "🟢 <b>СМЕНА ИДЁТ</b>"
        note = "<i>Таймер тикает. Хорошей смены!</i>"
    else:
        head = "⏸ <b>ПАУЗА</b>"
        note = "<i>Время не идёт. Жми «Пуск», когда вернёшься.</i>"
    return (
        "<b>💼  W O R K</b>\n"
        f"{LINE}\n"
        f"{head}\n\n"
        f"⏱ Отработано: <code>{fmt_hms(elapsed)}</code>\n"
        f"🕓 Начало смены: <b>{clock(started_at)}</b>\n"
        f"📅 Дата: {day(started_at)}\n"
        f"⏸ Перерывов: {pauses}\n"
        f"{LINE}\n"
        f"{note}"
    )


def finished_card(*, started_at: int, finished_at: int, elapsed: int) -> str:
    return (
        "<b>🏁  СМЕНА ЗАВЕРШЕНА</b>\n"
        f"{LINE}\n"
        f"🕓 Смена: <b>{clock(started_at)} — {clock(finished_at)}</b>\n"
        f"⏱ Чистое время: <b>{fmt_hours(elapsed)}</b>  "
        f"(<code>{fmt_hms(elapsed)}</code>)\n"
        f"{LINE}\n"
        "Теперь заполним <b>заявку на вывод</b>.\n"
        "<i>7 коротких вопросов — считать ничего не надо, всё сделает бот.</i>"
    )


def admin_shift_closed(
    *,
    full_name: str,
    username: str | None,
    user_id: int,
    started_at: int,
    finished_at: int,
    elapsed: int,
    pauses: int,
) -> str:
    return (
        "<b>🏁 СМЕНА ЗАКРЫТА</b>\n"
        f"{LINE}\n"
        f"👤 Воркер: <b>{full_name}</b>\n"
        f"🔗 Юзернейм: {'@' + username if username else '—'}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"{LINE}\n"
        f"🕓 Смена: <b>{clock(started_at)} — {clock(finished_at)}</b>  ({day(started_at)})\n"
        f"⏱ Отработано: <b>{fmt_hours(elapsed)}</b>  (<code>{fmt_hms(elapsed)}</code>)\n"
        f"⏸ Перерывов: {pauses}\n"
        f"{LINE}\n"
        "<i>Это время автоматически подставлено в отчёт. "
        "Работник заполняет заявку на вывод…</i>"
    )


# --- вопросы анкеты -------------------------------------------------------
def q_start() -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(1)}\n\n"
        "<b>1) Старт</b> — начальный баланс токена.\n\n"
        "<i>Пришли число, например:</i> <code>300</code>"
    )


def q_end(start: float) -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(2)}\n\n"
        f"✅ Старт: <b>{money(start)}</b>\n\n"
        "<b>2) Конец</b> — фактический баланс токена.\n\n"
        "<i>Пришли число, например:</i> <code>900</code>"
    )


def q_disputes(start: float, end: float) -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(3)}\n\n"
        f"✅ Старт: <b>{money(start)}</b>\n"
        f"✅ Конец: <b>{money(end)}</b>\n\n"
        "<b>3) Диспуты</b> — сумма в баксах.\n"
        "<i>Это бабки, зашедшие на реквизиты без сделки / неподтверждённые.</i>\n\n"
        "Диспуты вычитаются из фактического конечного баланса, "
        "и только потом считается профит.\n\n"
        "<i>Пришли число или нажми кнопку ниже.</i>"
    )


def q_hours() -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(4)}\n\n"
        "<b>4) Часы смены.</b>\n"
        "Таймер не найден — впиши время вручную.\n\n"
        "<i>Можно так:</i> <code>16:00 - 05:00</code>  <i>или просто</i> <code>13</code>"
    )


def q_blocks(shift_str: str | None = None) -> str:
    auto = (
        f"✅ <b>4) Часы смены:</b> {shift_str}  <i>(с таймера)</i>\n\n"
        if shift_str
        else ""
    )
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(5)}\n\n"
        f"{auto}"
        "<b>5) Блоки.</b>\n"
        "Были ли сегодня блоки? Если да — укажешь, на каких ЛК."
    )


def q_blocks_text() -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(5)}\n\n"
        "<b>5) На каких ЛК блоки?</b>\n\n"
        "<i>Например:</i> <code>ЛК 3, ЛК 7 — бан по верификации</code>"
    )


def q_blocks_sum(blocks_text: str) -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(5)}\n\n"
        f"✅ Блоки: <b>{blocks_text}</b>\n\n"
        "<b>5) На какую сумму блок?</b>\n"
        "<i>Сколько баксов заблокировано — цифрой.</i>\n\n"
        "<i>Например:</i> <code>250</code>"
    )


def by_hours_pay(p: Payout) -> float:
    """Сколько вышло бы по часам (3.5$ за целый час) — независимо от блоков."""
    return round(max(0, p.whole_hours) * 3.5, 2)


def q_problems() -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(6)}\n\n"
        "<b>6) Какие были сложности за сегодняшний рабочий день?</b>\n\n"
        "<i>Напиши текстом. Если сложностей не было — нажми «Пропустить».</i>"
    )


def q_plans() -> str:
    return (
        f"<b>📝 ЗАЯВКА НА ВЫВОД</b>\n{LINE}\n"
        f"{progress(7)}\n\n"
        "<b>7) Какие планы на завтра?</b>\n\n"
        "<i>Напиши текстом.</i>"
    )


def confirm_card(d: dict) -> str:
    blocks = d.get("blocks_text") or "нет"
    if d.get("blocks_text") and d.get("blocks_sum"):
        blocks = f"{d['blocks_text']} • на сумму {money(d['blocks_sum'])}"
    disputes = d.get("disputes") or 0
    return (
        f"<b>🔎 ПРОВЕРЬ ЗАЯВКУ</b>\n{LINE}\n"
        f"1) Старт: <b>{money(d['start'])}</b>\n"
        f"2) Конец: <b>{money(d['end'])}</b>\n"
        f"3) Диспуты: <b>{money(disputes)}</b>\n"
        f"4) Часы смены: <b>{d['shift_str']}</b>\n"
        f"5) Блоки: <b>{blocks}</b>\n"
        f"6) Сложности: {d.get('problems') or '—'}\n"
        f"7) Планы на завтра: {d.get('plans') or '—'}\n"
        f"{LINE}\n"
        "<i>Всё верно? Заявка уйдёт админу, а тебе покажу заработок за день.</i>"
    )


# --- итог для работника ---------------------------------------------------
def payout_card(p: Payout, shift_str: str) -> str:
    lines = [
        "<b>💰 ЗАРАБОТОК ЗА ДЕНЬ</b>",
        LINE,
        f"Профит открученный: <b>{money(p.profit)}</b>",
        f"Ставка: <b>{p.percent:g}%</b>",
        f"Расчёт: {money(p.profit)} / 100 × {p.percent:g} = <b>{money(p.percent_pay)}</b>",
    ]
    if p.has_blocks and p.whole_hours >= 1:
        lines.append(
            f"Фикс за блоки: {p.whole_hours} ч × 3.5$ = <b>{money(p.fix_pay)}</b>"
        )
    lines += [
        f"Смена: <b>{shift_str}</b>",
        LINE,
        f"🏆 <b>К ВЫПЛАТЕ: {money(p.total)}</b>  <i>({p.basis})</i>",
        "",
        "<i>Заявка отправлена админу. Хорошего отдыха!</i>",
    ]
    return "\n".join(lines)


# --- заявка для админа ----------------------------------------------------
def admin_report(
    *,
    report_id: int,
    who: str,
    date_str: str,
    p: Payout,
    shift_str: str,
    blocks_text: str | None,
    blocks_sum: float | None,
    problems: str,
    plans: str,
) -> str:
    clean_end = p.end - p.disputes
    blocks = blocks_text or "нет"
    if blocks_text and blocks_sum:
        blocks = f"{blocks_text} • на сумму {money(blocks_sum)}"
    hours_pay = by_hours_pay(p)
    lines = [
        f"<b>📋 ЗАЯВКА НА ВЫВОД №{report_id}</b>",
        f"👤 {who}   •   📅 {date_str}",
        LINE,
        f"<b>1) Старт (баланс токена):</b> {money(p.start)}",
        f"<b>2) Конец (факт. баланс):</b> {money(p.end)}",
        f"     ↳ диспуты: {money(p.disputes)} → чистый конец: {money(clean_end)}",
        f"<b>3) Профит:</b> {money(p.profit)}  →  ставка {p.percent:g}%",
        f"<b>4) Часы смены:</b> {shift_str}",
        f"<b>5) Блоки:</b> {blocks}",
        f"<b>6) Сложности:</b> {problems or '—'}",
        f"<b>7) Планы на завтра:</b> {plans or '—'}",
        LINE,
        "<b>💵 К ВЫПЛАТЕ РАБОТНИКУ</b>",
        f"   по профиту: {money(p.profit)} × {p.percent:g}% = <b>{money(p.percent_pay)}</b>",
        f"   по часам:   {p.whole_hours} ч × 3.5$ = <b>{money(hours_pay)}</b>",
        f"   <b>ИТОГ: {money(p.total)}</b>  <i>({p.basis})</i>",
    ]
    return "\n".join(lines)


# --- клавиатуры -----------------------------------------------------------
def kb_idle() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Начал работу", callback_data="work:start")
    kb.button(text="📊 Моя статистика", callback_data="work:stats")
    kb.button(text="❓ Как это работает", callback_data="work:help")
    kb.adjust(1, 2)
    return kb.as_markup()


def kb_running() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⏸ Пауза", callback_data="work:pause")
    kb.button(text="🔄 Обновить", callback_data="work:refresh")
    kb.button(text="⏹ Стоп работа", callback_data="work:stop")
    kb.adjust(2, 1)
    return kb.as_markup()


def kb_paused() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="▶️ Пуск", callback_data="work:resume")
    kb.button(text="🔄 Обновить", callback_data="work:refresh")
    kb.button(text="⏹ Стоп работа", callback_data="work:stop")
    kb.adjust(2, 1)
    return kb.as_markup()


def kb_no_disputes() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Диспутов не было", callback_data="form:nodisputes")
    return kb.as_markup()


def kb_blocks() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Блоков не было", callback_data="form:noblocks")
    kb.button(text="⛔️ Были блоки", callback_data="form:hasblocks")
    kb.adjust(1)
    return kb.as_markup()


def kb_unknown_sum() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🤷 Сумма неизвестна", callback_data="form:nosum")
    return kb.as_markup()


def kb_skip() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⏭ Пропустить", callback_data="form:skip")
    return kb.as_markup()


def kb_confirm() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить заявку", callback_data="form:send")
    kb.button(text="✏️ Заполнить заново", callback_data="form:restart")
    kb.button(text="❌ Отменить", callback_data="form:cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_admin_report(report_id: int, user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💸 Отметить выплаченным", callback_data=f"adm:paid:{report_id}")
    kb.button(text="✉️ Написать работнику", url=f"tg://user?id={user_id}")
    kb.adjust(1)
    return kb.as_markup()


def kb_contact_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Админ", url=f"https://t.me/{ADMIN_USERNAME}")]
        ]
    )


def help_text() -> str:
    return (
        f"<b>❓ КАК ЭТО РАБОТАЕТ</b>\n{LINE}\n"
        "<b>1.</b> Жмёшь «Начал работу» — идёт таймер.\n"
        "<b>2.</b> Ушёл на перерыв — «Пауза», вернулся — «Пуск».\n"
        "<b>3.</b> Конец смены — «Стоп работа», бот покажет часы.\n"
        "<b>4.</b> Заполняешь заявку: старт, конец, диспуты, блоки, "
        "сложности, планы.\n"
        "<b>5.</b> Заявка уходит админу, тебе — сумма заработка.\n"
        f"{LINE}\n"
        "<b>💵 Ставки от профита</b>\n"
        "до 300$ — 12%\n"
        "300–500$ — 13%\n"
        "500–800$ — 15%\n"
        "800$+ — 16%\n\n"
        "<b>⛔️ Если были блоки</b> — считается фикс "
        "<b>3.5$ за каждый целый час</b> смены.\n\n"
        "<b>⚖️ Диспуты</b> вычитаются из конечного баланса до расчёта профита."
    )
