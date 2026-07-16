from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def start_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Старт", callback_data="start")]
        ]
    )
    return kb

def topics_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Школа", callback_data="topic_school"),
                InlineKeyboardButton(text="Лагерь", callback_data="topic_lager")
            ],
            [
                InlineKeyboardButton(text="Погружение", callback_data="topic_pogrezh"),
                InlineKeyboardButton(text="Другое", callback_data="topic_other")
            ]
        ]
    )
    return kb

def back_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="back_to_topics")]
        ]
    )
    return kb

def meeting_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Записаться", callback_data="meeting_yes"),
                InlineKeyboardButton(text="Позже", callback_data="meeting_no")
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data="back_to_topics")
            ]
        ]
    )
    return kb

def other_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Оператор", callback_data="other_operator"),
                InlineKeyboardButton(text="Помещение", callback_data="other_premises")
            ],
            [
                InlineKeyboardButton(text="Отзывы", callback_data="other_reviews"),
                InlineKeyboardButton(text="Персонал", callback_data="other_staff")
            ],
            [
                InlineKeyboardButton(text="Мои записи", callback_data="other_my_appointments"),
                InlineKeyboardButton(text="Мои данные", callback_data="other_profile")
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data="back_to_topics")
            ]
        ]
    )
    return kb

def cancel_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
        ]
    )
    return kb

def appointment_action_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отменить запись", callback_data="appointment_cancel"),
                InlineKeyboardButton(text="Записаться еще", callback_data="appointment_new")
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data="back_to_topics")
            ]
        ]
    )
    return kb


# --- Напоминания ---

def refusal_reminder_btn():
    """Кнопки для напоминания тем, кто нажал «Позже» при выборе встречи."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Нет, спасибо", callback_data="remind_no"),
                InlineKeyboardButton(text="Ещё подумаю", callback_data="remind_later"),
            ],
            [
                InlineKeyboardButton(text="Записаться", callback_data="remind_book"),
            ]
        ]
    )
    return kb


# --- Админ-панель ---

def admin_menu_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Все записи", callback_data="admin_all"),
                InlineKeyboardButton(text="На сегодня", callback_data="admin_today")
            ],
            [
                InlineKeyboardButton(text="На завтра", callback_data="admin_tomorrow"),
                InlineKeyboardButton(text="На неделю", callback_data="admin_week")
            ],
            [
                InlineKeyboardButton(text="Удалить запись", callback_data="admin_delete")
            ],
            [
                InlineKeyboardButton(text="Тексты сообщений", callback_data="admin_texts"),
                InlineKeyboardButton(text="Выгрузить Excel", callback_data="admin_export")
            ],
            [
                InlineKeyboardButton(text="Закрыть", callback_data="admin_close")
            ]
        ]
    )
    return kb

def admin_delete_btn(appointment_id):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Удалить", callback_data=f"admin_confirm_delete_{appointment_id}")],
            [InlineKeyboardButton(text="Назад", callback_data="admin_delete")]
        ]
    )
    return kb

def admin_texts_list_btn(editable_messages):
    """Список сообщений для редактирования. editable_messages — список (key, label)."""
    builder = InlineKeyboardBuilder()
    for key, label in editable_messages:
        builder.button(text=label, callback_data=f"admtext_{key}")
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()

def admin_text_edit_btn():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_texts")]
        ]
    )
    return kb