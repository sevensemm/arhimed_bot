import sqlite3
from datetime import datetime

DB_NAME = 'leads.db'

def get_conn():
    """Создает подключение к БД. Включает поддержку внешних ключей."""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def _add_column_if_missing(conn, table: str, column: str, coltype: str):
    """Безопасно добавляет колонку в существующую таблицу, если её ещё нет."""
    cols = [row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {coltype}')

def _drop_column_if_present(conn, table: str, column: str):
    """Безопасно удаляет колонку, если она есть (поддерживается SQLite 3.35+)."""
    cols = [row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if column in cols:
        try:
            conn.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
        except sqlite3.OperationalError:
            # Старая версия SQLite не поддерживает DROP COLUMN — колонка
            # останется в базе физически, но бот больше её не использует.
            pass

def create_tables():
    """Создает таблицы базы данных при старте бота (и накатывает недостающие колонки)."""
    with get_conn() as conn:
        # Таблица лидов
        conn.execute('''
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                topic TEXT,
                name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        # Таблица записей на встречу
        conn.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date_text TEXT NOT NULL,
                time_text TEXT NOT NULL,
                status TEXT DEFAULT 'scheduled',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date_text, time_text)
            )
        ''')
        # Таблица кастомных (отредактированных админом) текстов сообщений
        conn.execute('''
            CREATE TABLE IF NOT EXISTS custom_messages (
                key TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                updated_at TEXT
            )
        ''')

        # Миграция: добавляем недостающие колонки в уже существующие БД
        _add_column_if_missing(conn, 'appointments', 'reminded', 'INTEGER DEFAULT 0')
        _add_column_if_missing(conn, 'leads', 'next_reminder_at', 'TEXT')
        # Миграция: класс ребёнка больше не хранится
        _drop_column_if_present(conn, 'leads', 'grade')


# --- РАБОТА С ЛИДАМИ (Пользователями) ---

def save_lead(user_id: int, username: str):
    """Инициализирует нового пользователя, если его еще нет в базе."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute('''
            INSERT OR IGNORE INTO leads (user_id, username, status, created_at, updated_at)
            VALUES (?, ?, 'new', ?, ?)
        ''', (user_id, username, now, now))

def update_lead_field(user_id: int, field_name: str, value: str):
    """Универсальная функция для обновления одиночных полей лида."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            f'UPDATE leads SET {field_name} = ?, updated_at = ? WHERE user_id = ?', 
            (value, now, user_id)
        )

# Возвращаем методы, которые вызывают хэндлеры в основном файле
def update_topic(user_id: int, topic: str):
    """Обновляет тему лида (требуется для main)."""
    update_lead_field(user_id, 'topic', topic)

def update_status(user_id: int, status: str):
    """Обновляет статус лида (требуется для main)."""
    update_lead_field(user_id, 'status', status)

def update_lead_full(data: dict):
    """Заполняет профиль лида при успешной записи на встречу."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute('''
            UPDATE leads 
            SET name = ?, phone = ?, status = 'meeting_scheduled', updated_at = ?
            WHERE user_id = ?
        ''', (data['name'], data['phone'], now, data['user_id']))

def update_lead_profile(user_id: int, name: str, phone: str):
    """
    Обновляет ФИО/телефон лида, не трогая его статус записи
    (в отличие от update_lead_full, используется для правки данных
    из вкладки «Другое», а не в момент бронирования встречи).
    """
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute('''
            UPDATE leads
            SET name = ?, phone = ?, updated_at = ?
            WHERE user_id = ?
        ''', (name, phone, now, user_id))

def get_lead(user_id: int) -> tuple:
    """Возвращает всю информацию о лиде."""
    with get_conn() as conn:
        return conn.execute('SELECT * FROM leads WHERE user_id = ?', (user_id,)).fetchone()


# --- РАБОТА С ЗАПИСЯМИ (Календарь и Время) ---

def book_appointment(user_id: int, date_text: str, time_text: str):
    """Бронирует слот времени. Сработает UNIQUE, если слот уже занят."""
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO appointments (user_id, date_text, time_text, status)
            VALUES (?, ?, ?, 'scheduled')
        ''', (user_id, date_text, time_text))

def cancel_appointment(user_id: int, date_text: str, time_text: str):
    """Переводит запись пользователя в статус 'отменена' (освобождает слот)."""
    with get_conn() as conn:
        conn.execute('''
            UPDATE appointments 
            SET status = 'cancelled' 
            WHERE user_id = ? AND date_text = ? AND time_text = ?
        ''', (user_id, date_text, time_text))

def get_booked_times(date_text: str) -> list:
    """Возвращает список только занятого времени (часов) на выбранную дату."""
    with get_conn() as conn:
        rows = conn.execute('''
            SELECT time_text FROM appointments 
            WHERE date_text = ? AND status = 'scheduled'
        ''', (date_text,)).fetchall()
        return [row[0] for row in rows]

def get_user_appointments(user_id: int) -> list:
    """Возвращает все активные (по статусу) записи конкретного пользователя, включая прошедшие даты."""
    with get_conn() as conn:
        return conn.execute('''
            SELECT id, date_text, time_text, status FROM appointments 
            WHERE user_id = ? AND status = 'scheduled'
            ORDER BY date_text, time_text
        ''', (user_id,)).fetchall()

def get_active_user_appointments(user_id: int) -> list:
    """
    Возвращает записи пользователя, которые ещё актуальны: статус 'scheduled'
    И дата встречи не в прошлом. Именно эти записи считаются "занимающими слот"
    при проверке "нельзя записаться дважды" — прошедшие и отменённые не мешают.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        return conn.execute('''
            SELECT id, date_text, time_text, status FROM appointments 
            WHERE user_id = ? AND status = 'scheduled' AND date_text >= ?
            ORDER BY date_text, time_text
        ''', (user_id, today)).fetchall()

def get_appointment_by_id(appointment_id: int) -> tuple:
    """Возвращает запись по её ID (id, user_id, date_text, time_text, status)."""
    with get_conn() as conn:
        return conn.execute('''
            SELECT id, user_id, date_text, time_text, status FROM appointments WHERE id = ?
        ''', (appointment_id,)).fetchone()

def cancel_appointment_by_id(appointment_id: int):
    """Отменяет запись по её ID (освобождает слот)."""
    with get_conn() as conn:
        conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appointment_id,))


# --- ПАНЕЛЬ АДМИНИСТРАТОРА / СЛУЖЕБНЫЕ ЗАПРОСЫ ---

def get_appointment_by_date_time(date_text: str, time_text: str) -> tuple:
    """Проверяет статус конкретного слота."""
    with get_conn() as conn:
        return conn.execute('''
            SELECT user_id, status FROM appointments 
            WHERE date_text = ? AND time_text = ?
        ''', (date_text, time_text)).fetchone()

def get_all_appointments() -> list:
    """Возвращает вообще все активные записи в системе (для админа)."""
    with get_conn() as conn:
        return conn.execute('''
            SELECT id, user_id, date_text, time_text, status, created_at 
            FROM appointments WHERE status = 'scheduled'
            ORDER BY date_text, time_text
        ''').fetchall()

def get_appointments_by_date(date_text: str) -> list:
    """Возвращает список записей (клиентов) на конкретный день."""
    with get_conn() as conn:
        return conn.execute('''
            SELECT user_id, time_text FROM appointments 
            WHERE date_text = ? AND status = 'scheduled'
            ORDER BY time_text
        ''', (date_text,)).fetchall()

def delete_appointment(appointment_id: int):
    """Полностью удаляет запись из базы данных по ID."""
    with get_conn() as conn:
        conn.execute('DELETE FROM appointments WHERE id = ?', (appointment_id,))


# --- НАПОМИНАНИЯ ---

def get_appointments_for_reminder(date_text: str) -> list:
    """Записи на указанную дату (обычно 'завтра'), по которым ещё не отправлено напоминание."""
    with get_conn() as conn:
        return conn.execute('''
            SELECT id, user_id, date_text, time_text FROM appointments
            WHERE date_text = ? AND status = 'scheduled' AND (reminded IS NULL OR reminded = 0)
        ''', (date_text,)).fetchall()

def mark_appointment_reminded(appointment_id: int):
    """Отмечает, что напоминание по записи уже отправлено (чтобы не дублировать)."""
    with get_conn() as conn:
        conn.execute('UPDATE appointments SET reminded = 1 WHERE id = ?', (appointment_id,))

def get_leads_for_refusal_reminder(now_iso: str) -> list:
    """Лиды со статусом 'refused' (нажали «Позже»), для которых наступило время напомнить."""
    with get_conn() as conn:
        return conn.execute('''
            SELECT user_id FROM leads
            WHERE status = 'refused' AND next_reminder_at IS NOT NULL AND next_reminder_at <= ?
        ''', (now_iso,)).fetchall()

def set_next_reminder(user_id: int, next_reminder_at):
    """Устанавливает (или сбрасывает, если None) время следующего напоминания для лида."""
    with get_conn() as conn:
        conn.execute('UPDATE leads SET next_reminder_at = ? WHERE user_id = ?', (next_reminder_at, user_id))

def set_lead_status_and_reminder(user_id: int, status: str, next_reminder_at):
    """Одновременно обновляет статус лида и время следующего напоминания."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute('''
            UPDATE leads SET status = ?, next_reminder_at = ?, updated_at = ?
            WHERE user_id = ?
        ''', (status, next_reminder_at, now, user_id))


# --- КАСТОМНЫЕ ТЕКСТЫ СООБЩЕНИЙ (редактируются админом) ---

def get_msg(key: str, default: str) -> str:
    """Возвращает текст сообщения: отредактированный админом (если есть) или дефолтный."""
    with get_conn() as conn:
        row = conn.execute('SELECT text FROM custom_messages WHERE key = ?', (key,)).fetchone()
        return row[0] if row else default

def set_msg(key: str, text: str):
    """Сохраняет отредактированный админом текст сообщения."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute('''
            INSERT INTO custom_messages (key, text, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET text = excluded.text, updated_at = excluded.updated_at
        ''', (key, text, now))


# --- ЭКСПОРТ ДАННЫХ ---

def get_export_rows() -> list:
    """
    Возвращает все строки для экспорта в Excel: данные лида + все его записи
    (включая отменённые — статус записи важен для отчёта).
    Если у лида нет ни одной записи, поля записи будут NULL.
    """
    with get_conn() as conn:
        return conn.execute('''
            SELECT
                l.user_id, l.username, l.name, l.phone,
                l.topic, l.status, l.created_at,
                a.date_text, a.time_text, a.status
            FROM leads l
            LEFT JOIN appointments a ON a.user_id = l.user_id
            ORDER BY l.user_id, a.date_text, a.time_text
        ''').fetchall()