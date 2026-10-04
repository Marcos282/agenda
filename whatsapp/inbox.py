"""SQLite inbox isolated from the scheduling database."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from django.conf import settings


@contextmanager
def database():
    path = Path(settings.WHATSAPP_TESTS_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute('''CREATE TABLE IF NOT EXISTS received_messages (
            tenant INTEGER NOT NULL, message_id TEXT NOT NULL, number TEXT NOT NULL,
            text TEXT NOT NULL, received_at TEXT NOT NULL,
            PRIMARY KEY (tenant, message_id))''')
        connection.execute('CREATE INDEX IF NOT EXISTS inbox_conversation ON received_messages (tenant, number, received_at)')
        yield connection
        connection.commit()
    finally:
        connection.close()


def save_message(tenant_id, message_id, number, text):
    with database() as connection:
        cursor = connection.execute(
            'INSERT OR IGNORE INTO received_messages VALUES (?, ?, ?, ?, ?)',
            (tenant_id, message_id, number, text, datetime.now(timezone.utc).isoformat()),
        )
        return bool(cursor.rowcount)


def messages_for(tenant_id, number):
    with database() as connection:
        rows = connection.execute('''SELECT message_id, text, received_at FROM received_messages
            WHERE tenant = ? AND number = ? ORDER BY received_at DESC LIMIT 50''',
            (tenant_id, number)).fetchall()
        return [dict(row, sent=False) for row in rows]
