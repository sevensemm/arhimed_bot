import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, FSInputFile, BotCommand
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio

from openpyxl import Workbook

from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback

from config import TOKEN, ADMIN_ID
import messages
from messages import *
from keyboards import *
from database import *

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

create_tables()

class States(StatesGroup):
    topic = State()
    name = State()
    phone = State()
    grade = State()
    other = State()
    appointment_date = State()
    appointment_time = State()
    appointment_cancel = State()
    admin_delete = State()
    admin_edit_text = State()
    my_appointments = State()


# ---------------------------------------------------------------------------
# ХЕЛПЕРЫ ДЛЯ ЕДИНООБРАЗНОЙ РАБОТЫ С СООБЩЕНИЯМИ
#
# Договорённость по структуре бота:
#   — обычная кнопка (переход "вперёд")  -> старое сообщение удаляется,
#     отправляется новое;
#   — кнопка "Назад" / "Отмена"          -> сообщение редактируется на месте,
#     ничего не удаляется и не отправляется заново.
#
# Раньше бот пытался удалить одно и то же сообщение дважды (через
# state['last_message_id'] и через callback.message), из-за чего Telegram
# кидал исключение "message to delete not found" и хендлер обрывался,
# не успев отправить пользователю ответ. Теперь удаление всегда безопасное
# (обёрнуто в try/except), а отдельный last_message_id больше не нужен —
# везде используется id сообщения, к которому прикреплена нажатая кнопка.
# ---------------------------------------------------------------------------

async def safe_delete(message: Message):
    """Удаляет сообщение, не роняя хендлер, если оно уже удалено/недоступно."""
    try:
        await message.delete()
    except Exception:
        pass

async def send_new(message: Message, text: str, reply_markup=None) -> Message:
    """Переход 'вперёд': удаляет старое сообщение и присылает новое."""
    await safe_delete(message)
    return await message.answer(text, reply_markup=reply_markup)

async def edit_in_place(message: Message, text: str, reply_markup=None) -> Message:
    """Переход 'назад'/'отмена': редактирует текущее сообщение без удаления."""
    try:
        return await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        # На случай, если сообщение нельзя отредактировать (например, это
        # был документ, а не текст) — подстраховка тем же способом, что и раньше.
        await safe_delete(message)
        return await message.answer(text, reply_markup=reply_markup)


def m(key: str) -> str:
    """Возвращает актуальный (возможно отредактированный админом) текст сообщения."""
    return get_msg(key, getattr(messages, key))


def notify_admins(text: str):
    """Возвращает корутину рассылки текста всем администраторам."""
    async def _send():
        for admin_id in ADMIN_ID:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logging.warning(f"Не удалось отправить сообщение админу {admin_id}: {e}")
    return _send()


# ---------------------------------------------------------------------------
# ОСНОВНОЙ СЦЕНАРИЙ
# ---------------------------------------------------------------------------

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    save_lead(message.from_user.id, message.from_user.username)
    await state.clear()
    await message.answer(m("WELCOME"), reply_markup=start_btn())

@dp.callback_query(lambda c: c.data == "start")
async def choose_topic(callback: CallbackQuery):
    await send_new(callback.message, m("CHOOSE_TOPIC"), topics_btn())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("topic_"))
async def topic_handler(callback: CallbackQuery, state: FSMContext):
    topic = callback.data.replace("topic_", "")
    update_topic(callback.from_user.id, topic)

    if topic == "school":
        await send_new(callback.message, m("TOPIC_SCHOOL"), meeting_btn())
        await state.set_state(States.topic)
    elif topic == "lager":
        await send_new(callback.message, m("TOPIC_LAGER"), back_btn())
        await state.clear()
    elif topic == "pogrezh":
        await send_new(callback.message, m("TOPIC_POGREZH"), back_btn())
        await state.clear()
    elif topic == "other":
        await send_new(callback.message, m("TOPIC_OTHER"), other_btn())
        await state.set_state(States.other)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("meeting_"), StateFilter(States.topic))
async def meeting_handler(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("meeting_", "")
    user_id = callback.from_user.id

    if action == "yes":
        existing = get_user_appointments(user_id)
        if existing:
            date_text, time_text, status = existing[0]
            await send_new(
                callback.message,
                m("APPOINTMENT_EXISTS").format(date_text, time_text),
                appointment_action_btn()
            )
            await state.set_state(States.appointment_cancel)
        else:
            await show_calendar(callback.message, state, edit=False)
    elif action == "no":
        set_lead_status_and_reminder(
            user_id, "refused", (datetime.now() + timedelta(days=2)).isoformat()
        )
        await send_new(callback.message, m("MEETING_NO"), back_btn())
        await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("appointment_"), StateFilter(States.appointment_cancel))
async def appointment_action_handler(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("appointment_", "")
    user_id = callback.from_user.id

    if action == "cancel":
        existing = get_user_appointments(user_id)
        if existing:
            date_text, time_text, status = existing[0]
            cancel_appointment(user_id, date_text, time_text)
            await send_new(
                callback.message,
                m("APPOINTMENT_CANCELLED").format(date_text, time_text),
                back_btn()
            )
            await state.clear()
    elif action == "new":
        await show_calendar(callback.message, state, edit=False)
    await callback.answer()

@dp.callback_query(SimpleCalendarCallback.filter())
async def process_calendar(callback: CallbackQuery, callback_data: SimpleCalendarCallback, state: FSMContext):
    calendar = SimpleCalendar(locale='ru_RU', show_alerts=True)
    calendar.set_dates_range(datetime.now(), datetime.now() + timedelta(days=30))

    selected, date = await calendar.process_selection(callback, callback_data)
    if selected:
        if date.weekday() >= 5:  # 5 = суббота, 6 = воскресенье
            await callback.answer(
                "Мы не работаем по выходным. Пожалуйста, выберите будний день (Пн–Пт).",
                show_alert=True
            )
            return
        date_text = date.strftime("%Y-%m-%d")
        await state.update_data(selected_date=date_text)
        await show_time_slots(callback.message, date_text, state)

async def show_calendar(message: Message, state: FSMContext, edit: bool):
    """
    edit=False: обычный переход "вперёд" (старое сообщение удаляется, новое отправляется).
    edit=True: переход "назад" (например, из выбора времени назад к календарю) —
               сообщение редактируется на месте.
    """
    calendar = SimpleCalendar(locale='ru_RU', show_alerts=True)
    calendar.set_dates_range(datetime.now(), datetime.now() + timedelta(days=30))
    markup = await calendar.start_calendar()

    if edit:
        await edit_in_place(message, m("MEETING_YES"), markup)
    else:
        await send_new(message, m("MEETING_YES"), markup)
    await state.set_state(States.appointment_date)

async def show_time_slots(message: Message, date_text: str, state: FSMContext):
    booked_times = get_booked_times(date_text)
    builder = InlineKeyboardBuilder()

    for time_slot in WORKING_HOURS:
        if time_slot in booked_times:
            builder.button(
                text=f"🔒 {time_slot}",
                callback_data="time_booked"
            )
        else:
            builder.button(
                text=f"🟢 {time_slot}",
                callback_data=f"time_{time_slot}"
            )

    builder.button(text="Назад", callback_data="back_to_calendar")
    builder.adjust(2)

    # Переход "вперёд" от календаря к списку времени
    await send_new(message, f"Выберите время на {date_text}:", builder.as_markup())
    await state.set_state(States.appointment_time)

@dp.callback_query(lambda c: c.data.startswith("time_"), StateFilter(States.appointment_time))
async def time_selection_handler(callback: CallbackQuery, state: FSMContext):
    if callback.data == "time_booked":
        await callback.answer("Это время уже занято", show_alert=True)
        return

    time_slot = callback.data.replace("time_", "")
    data = await state.get_data()
    date_text = data.get("selected_date")
    user_id = callback.from_user.id

    if get_appointment_by_date_time(date_text, time_slot):
        await callback.answer("Это время уже занято", show_alert=True)
        return

    book_appointment(user_id, date_text, time_slot)

    # Пользователь всё-таки записался сам — отменяем отложенное напоминание
    # "вы хотели записаться" (не нужно спамить того, кто уже записался).
    set_next_reminder(user_id, None)

    lead = get_lead(user_id)
    name, phone, grade = (lead[4], lead[5], lead[6]) if lead else (None, None, None)

    if name and phone and grade:
        # Данные уже есть в профиле — повторно не спрашиваем
        update_status(user_id, "meeting_scheduled")
        await send_new(
            callback.message,
            m("APPOINTMENT_BOOKED").format(date_text, time_slot),
            back_btn()
        )
        await notify_admins(
            f"Новая запись на встречу (данные лида уже были в базе):\n"
            f"ФИО: {name}\nТелефон: {phone}\nКласс: {grade}\n"
            f"Дата/время: {date_text} {time_slot}\nUser ID: {user_id}"
        )
        await state.clear()
    else:
        # Донабираем данные лида (ФИО/телефон/класс), чтобы они попали
        # в профиль лида и в Excel-выгрузку для админа.
        await state.update_data(booked_date=date_text, booked_time=time_slot)
        await send_new(callback.message, m("NAME_PROMPT"), cancel_btn())
        await state.set_state(States.name)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_calendar", StateFilter(States.appointment_time))
async def back_to_calendar(callback: CallbackQuery, state: FSMContext):
    # Кнопка "Назад" -> редактируем сообщение на месте
    await show_calendar(callback.message, state, edit=True)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("other_"), StateFilter(States.other))
async def other_handler(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("other_", "")
    user_id = callback.from_user.id

    if action == "operator":
        # Один экран с текстом и просьбой описать вопрос, вместо двух подряд сообщений
        await send_new(callback.message, m("OTHER_OPERATOR"), cancel_btn())
        await state.set_state(States.other)
    elif action == "premises":
        await send_new(callback.message, m("OTHER_PREMISES"), back_btn())
        await state.clear()
    elif action == "reviews":
        await send_new(callback.message, m("OTHER_REVIEWS"), back_btn())
        await state.clear()
    elif action == "staff":
        await send_new(callback.message, m("OTHER_STAFF"), back_btn())
        await state.clear()
    elif action == "my_appointments":
        await show_my_appointments(callback.message, user_id, state)
    elif action == "profile":
        await state.clear()
        await show_profile(callback.message, user_id)
    await callback.answer()

async def show_profile(message: Message, user_id: int):
    lead = get_lead(user_id)
    name, phone, grade = (lead[4], lead[5], lead[6]) if lead else (None, None, None)

    if name and phone and grade:
        text = f"Ваши данные:\n\nФИО: {name}\nТелефон: {phone}\nКласс: {grade}"
    else:
        text = "Вы ещё не указывали свои данные."

    builder = InlineKeyboardBuilder()
    builder.button(text="Изменить данные", callback_data="profile_edit")
    builder.button(text="Назад", callback_data="back_to_topics")
    builder.adjust(1)

    await send_new(message, text, builder.as_markup())

@dp.callback_query(lambda c: c.data == "profile_edit")
async def profile_edit_start(callback: CallbackQuery, state: FSMContext):
    # Явно очищаем state, чтобы это не спутали с процессом бронирования
    # (иначе get_grade решит, что нужно ещё и записать на встречу)
    await state.clear()
    await send_new(callback.message, m("NAME_PROMPT"), cancel_btn())
    await state.set_state(States.name)
    await callback.answer()

async def show_my_appointments(message: Message, user_id: int, state: FSMContext):
    appointments = get_user_appointments(user_id)

    if not appointments:
        await send_new(message, m("NO_APPOINTMENTS"), back_btn())
        return

    builder = InlineKeyboardBuilder()
    for date_text, time_text, status in appointments:
        builder.button(
            text=f"{date_text} {time_text} - Отменить",
            callback_data=f"my_cancel_{date_text}_{time_text}"
        )
    builder.button(text="Назад", callback_data="back_to_topics")
    builder.adjust(1)

    await send_new(message, "Ваши записи:", builder.as_markup())
    await state.set_state(States.my_appointments)

@dp.callback_query(lambda c: c.data.startswith("my_cancel_"), StateFilter(States.my_appointments))
async def my_cancel_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    parts = callback.data.replace("my_cancel_", "").split("_")
    date_text = f"{parts[0]}-{parts[1]}-{parts[2]}"
    time_text = parts[3]

    cancel_appointment(user_id, date_text, time_text)

    await send_new(
        callback.message,
        m("APPOINTMENT_CANCELLED").format(date_text, time_text),
        back_btn()
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_topics")
async def back_to_topics(callback: CallbackQuery, state: FSMContext):
    # Кнопка "Назад" -> редактируем текущее сообщение, не удаляя и не создавая новое
    await state.clear()
    await edit_in_place(callback.message, m("CHOOSE_TOPIC"), topics_btn())
    await callback.answer()

@dp.message(StateFilter(States.name))
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(m("PHONE_PROMPT"), reply_markup=cancel_btn())
    await state.set_state(States.phone)

@dp.message(StateFilter(States.phone))
async def get_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer(m("GRADE_PROMPT"), reply_markup=cancel_btn())
    await state.set_state(States.grade)

@dp.message(StateFilter(States.grade))
async def get_grade(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data.get("name")
    phone = data.get("phone")
    grade = message.text
    user_id = message.from_user.id
    date_text = data.get("booked_date")
    time_text = data.get("booked_time")

    if date_text and time_text:
        # Сценарий: донабор данных в процессе записи на встречу
        update_lead_full({"name": name, "phone": phone, "grade": grade, "user_id": user_id})
        await message.answer(
            m("APPOINTMENT_BOOKED").format(date_text, time_text),
            reply_markup=back_btn()
        )
        await notify_admins(
            f"Новая запись на встречу:\n"
            f"ФИО: {name}\nТелефон: {phone}\nКласс: {grade}\n"
            f"Дата/время: {date_text} {time_text}\nUser ID: {user_id}"
        )
    else:
        # Сценарий: пользователь просто редактирует свои данные из вкладки "Другое"
        update_lead_profile(user_id, name, phone, grade)
        await message.answer("Ваши данные обновлены.", reply_markup=back_btn())

    await state.clear()

@dp.message(StateFilter(States.other))
async def other_question(message: Message, state: FSMContext):
    await notify_admins(f"Вопрос от {message.from_user.username}: {message.text}")
    await message.answer("Ваш вопрос отправлен. Мы ответим в ближайшее время.", reply_markup=back_btn())
    await state.clear()

@dp.callback_query(lambda c: c.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    # "Отмена" ведёт себя как "Назад": редактируем сообщение, возвращая к темам.
    # Если слот уже был забронирован (мы в процессе донабора ФИО/телефона/класса),
    # а пользователь передумал — саму запись тоже нужно отменить, иначе слот
    # останется "висеть" занятым без данных лида.
    data = await state.get_data()
    booked_date = data.get("booked_date")
    booked_time = data.get("booked_time")
    if booked_date and booked_time:
        cancel_appointment(callback.from_user.id, booked_date, booked_time)

    await state.clear()
    await edit_in_place(callback.message, m("CHOOSE_TOPIC"), topics_btn())
    await callback.answer()


# ---------------------------------------------------------------------------
# НАПОМИНАНИЯ
# ---------------------------------------------------------------------------

async def check_appointment_reminders():
    """За 1 день до встречи присылает простое текстовое напоминание (без кнопок)."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    for apt_id, user_id, date_text, time_text in get_appointments_for_reminder(tomorrow):
        try:
            text = m("APPOINTMENT_REMINDER").format(date_text, time_text)
            await bot.send_message(user_id, text)
        except Exception as e:
            logging.warning(f"Не удалось отправить напоминание о встрече user_id={user_id}: {e}")
        finally:
            mark_appointment_reminded(apt_id)

async def check_refusal_reminders():
    """
    Тем, кто нажал «Позже»: первое напоминание — через 2 дня, дальше повторяется
    ещё через 2 дня, но только если пользователь сам нажал «Ещё подумаю».
    """
    now_iso = datetime.now().isoformat()
    for (user_id,) in get_leads_for_refusal_reminder(now_iso):
        try:
            await bot.send_message(user_id, m("REMINDER"), reply_markup=refusal_reminder_btn())
        except Exception as e:
            logging.warning(f"Не удалось отправить напоминание о записи user_id={user_id}: {e}")
        finally:
            # Сбрасываем время следующего напоминания: новое будет назначено
            # только если пользователь нажмёт "Ещё подумаю"
            set_next_reminder(user_id, None)

async def reminder_loop():
    """Фоновая задача: раз в час проверяет, кому пора напомнить."""
    while True:
        try:
            await check_appointment_reminders()
            await check_refusal_reminders()
        except Exception as e:
            logging.error(f"Ошибка в reminder_loop: {e}")
        await asyncio.sleep(3600)

@dp.callback_query(lambda c: c.data == "remind_no")
async def remind_no_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    set_lead_status_and_reminder(user_id, "declined", None)
    await edit_in_place(callback.message, m("REMINDER_DECLINED_ACK"), None)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "remind_later")
async def remind_later_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    next_dt = (datetime.now() + timedelta(days=2)).isoformat()
    set_lead_status_and_reminder(user_id, "refused", next_dt)
    await edit_in_place(callback.message, m("REMINDER_LATER_ACK"), None)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "remind_book")
async def remind_book_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    set_next_reminder(user_id, None)

    existing = get_user_appointments(user_id)
    if existing:
        date_text, time_text, status = existing[0]
        await edit_in_place(
            callback.message,
            m("APPOINTMENT_EXISTS").format(date_text, time_text),
            appointment_action_btn()
        )
        await state.set_state(States.appointment_cancel)
    else:
        await show_calendar(callback.message, state, edit=True)
    await callback.answer()


# ---------------------------------------------------------------------------
# АДМИН-ПАНЕЛЬ
# ---------------------------------------------------------------------------

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    await message.answer("Панель администратора:", reply_markup=admin_menu_btn())

@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_handlers(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    action = callback.data.replace("admin_", "")

    if action == "all":
        await show_all_appointments(callback.message)
    elif action == "today":
        await show_appointments_by_date(callback.message, datetime.now().strftime("%Y-%m-%d"))
    elif action == "tomorrow":
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        await show_appointments_by_date(callback.message, tomorrow)
    elif action == "week":
        await show_week_appointments(callback.message)
    elif action == "delete":
        await state.clear()
        await show_delete_list(callback.message, state)
    elif action.startswith("confirm_delete_"):
        await confirm_delete(callback.message, callback.data)
        await state.clear()
    elif action == "texts":
        await state.clear()
        await edit_in_place(callback.message, "Выберите сообщение для редактирования:",
                             admin_texts_list_btn(EDITABLE_MESSAGES))
    elif action == "export":
        await callback.answer("Формирую файл, подождите...")
        await send_export_file(callback.message)
    elif action == "back":
        await state.clear()
        await edit_in_place(callback.message, "Панель администратора:", admin_menu_btn())
    elif action == "close":
        await safe_delete(callback.message)
        await callback.answer()
        return
    await callback.answer()

async def show_all_appointments(message: Message):
    appointments = get_all_appointments()
    if not appointments:
        await edit_in_place(message, "Нет активных записей.", admin_menu_btn())
        return

    text = "Все записи:\n\n"
    for apt in appointments:
        text += f"ID: {apt[0]} | User: {apt[1]} | {apt[2]} {apt[3]} | {apt[4]}\n"

    await edit_in_place(message, text, admin_menu_btn())

async def show_appointments_by_date(message: Message, date_text: str):
    appointments = get_appointments_by_date(date_text)
    if not appointments:
        await edit_in_place(message, f"Нет записей на {date_text}.", admin_menu_btn())
        return

    text = f"Записи на {date_text}:\n\n"
    for apt in appointments:
        text += f"User: {apt[0]} | Время: {apt[1]}\n"

    await edit_in_place(message, text, admin_menu_btn())

async def show_week_appointments(message: Message):
    today = datetime.now()
    text = "Записи на неделю:\n\n"

    for i in range(7):
        date = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        appointments = get_appointments_by_date(date)
        text += f"\n{date}:\n"
        if appointments:
            for apt in appointments:
                text += f"  {apt[1]} - User: {apt[0]}\n"
        else:
            text += "  Нет записей\n"

    await edit_in_place(message, text, admin_menu_btn())

async def show_delete_list(message: Message, state: FSMContext):
    appointments = get_all_appointments()
    if not appointments:
        await edit_in_place(message, "Нет записей для удаления.", admin_menu_btn())
        return

    builder = InlineKeyboardBuilder()
    for apt in appointments:
        builder.button(
            text=f"{apt[2]} {apt[3]} - User: {apt[1]}",
            callback_data=f"admin_select_delete_{apt[0]}"
        )
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)

    await edit_in_place(message, "Выберите запись для удаления:", builder.as_markup())
    await state.set_state(States.admin_delete)

@dp.callback_query(lambda c: c.data.startswith("admin_select_delete_"), StateFilter(States.admin_delete))
async def select_delete(callback: CallbackQuery, state: FSMContext):
    apt_id = int(callback.data.replace("admin_select_delete_", ""))
    await state.update_data(delete_id=apt_id)

    await edit_in_place(callback.message, "Подтвердите удаление:", admin_delete_btn(apt_id))
    await callback.answer()

async def confirm_delete(message: Message, callback_data: str):
    apt_id = int(callback_data.replace("admin_confirm_delete_", ""))
    delete_appointment(apt_id)
    await edit_in_place(message, "Запись удалена.", admin_menu_btn())


# --- Редактирование текстов сообщений ---

@dp.callback_query(lambda c: c.data.startswith("admtext_"))
async def admin_text_select(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    key = callback.data.replace("admtext_", "")
    labels = dict(EDITABLE_MESSAGES)
    label = labels.get(key, key)
    current_text = m(key)

    await state.update_data(
        edit_key=key,
        panel_chat_id=callback.message.chat.id,
        panel_message_id=callback.message.message_id,
    )
    await state.set_state(States.admin_edit_text)

    prompt = (
        f"Редактирование: «{label}»\n\n"
        f"Текущий текст:\n{current_text}\n\n"
        f"Пришлите новый текст следующим сообщением."
    )
    await edit_in_place(callback.message, prompt, admin_text_edit_btn())
    await callback.answer()

@dp.message(StateFilter(States.admin_edit_text))
async def admin_text_save(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_ID:
        return

    data = await state.get_data()
    key = data.get("edit_key")
    panel_chat_id = data.get("panel_chat_id")
    panel_message_id = data.get("panel_message_id")

    if not key:
        await state.clear()
        return

    set_msg(key, message.text)
    await safe_delete(message)  # убираем из чата само сообщение с новым текстом

    labels = dict(EDITABLE_MESSAGES)
    label = labels.get(key, key)
    confirm_text = f"Текст «{label}» обновлён.\n\nВыберите следующее сообщение для редактирования:"

    try:
        await bot.edit_message_text(
            chat_id=panel_chat_id,
            message_id=panel_message_id,
            text=confirm_text,
            reply_markup=admin_texts_list_btn(EDITABLE_MESSAGES),
        )
    except Exception as e:
        logging.warning(f"Не удалось обновить панель админа: {e}")
        await bot.send_message(panel_chat_id, confirm_text, reply_markup=admin_texts_list_btn(EDITABLE_MESSAGES))

    await state.clear()


# --- Экспорт в Excel ---

def build_export_workbook() -> str:
    """Строит .xlsx с лидами и их записями, возвращает путь к файлу."""
    rows = get_export_rows()

    wb = Workbook()
    ws = wb.active
    ws.title = "Записи"

    headers = [
        "User ID", "Username", "ФИО", "Телефон", "Класс",
        "Тема", "Статус лида", "Создан",
        "Дата встречи", "Время встречи", "Статус записи",
    ]
    ws.append(headers)

    for row in rows:
        ws.append(list(row))

    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 40)

    os.makedirs("exports", exist_ok=True)
    filename = f"exports/leads_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(filename)
    return filename

async def send_export_file(message: Message):
    filepath = build_export_workbook()
    try:
        await message.answer_document(
            FSInputFile(filepath),
            caption="Экспорт лидов и записей"
        )
    finally:
        try:
            os.remove(filepath)
        except OSError:
            pass


async def main():
    # Регистрируем /start в меню команд бота — тогда Telegram сразу показывает
    # кликабельную кнопку "START" для тех, кто открывает чат с ботом впервые.
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать работу с ботом"),
    ])
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())