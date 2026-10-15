import sqlite3
from pathlib import Path
from .config import DB_PATH
import json


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema():
    """初始化中间层数据库"""
    conn = get_connection()
    try:
        # 迁移：旧版 messages 缺少 source_file（分片去重键）。微信分片 DB（message_0/message_1…）
        # 中同名 Msg_ 表的 local_id 各自从 1 开始，仅靠 (session, local_id) 去重会互相覆盖丢消息。
        # 缓存库可重建，直接删表重建，并清空指纹触发下次全量导入。
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
            if cols and "source_file" not in cols:
                conn.executescript("""
                    DROP TABLE IF EXISTS messages;
                    DROP TABLE IF EXISTS messages_fts;
                """)
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('source_fingerprint', '')"
                )
                conn.commit()
        except Exception:
            pass

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            username TEXT PRIMARY KEY,
            type TEXT,
            display_name TEXT,
            avatar_md5 TEXT,
            message_count INTEGER DEFAULT 0,
            first_time INTEGER,
            last_time INTEGER,
            last_msg_preview TEXT,
            is_hidden INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_username TEXT NOT NULL,
            local_id INTEGER NOT NULL,
            source_file TEXT NOT NULL DEFAULT '',
            create_time INTEGER,
            sender_username TEXT,
            sender_display_name TEXT,
            local_type INTEGER,
            content TEXT,
            media_md5 TEXT,
            is_self INTEGER DEFAULT 0,
            raw_json TEXT,
            UNIQUE(session_username, source_file, local_id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session_time ON messages(session_username, create_time DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(create_time DESC);

        CREATE TABLE IF NOT EXISTS contacts (
            username TEXT PRIMARY KEY,
            local_type INTEGER,
            alias TEXT,
            remark TEXT,
            nick_name TEXT,
            head_img_md5 TEXT,
            display_name TEXT,
            delete_flag INTEGER DEFAULT 0,
            chat_room_notify INTEGER DEFAULT 0,
            is_in_chat_room INTEGER DEFAULT 0
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content, sender_display_name,
            content='messages', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );

        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content, sender_display_name)
            VALUES (new.id, new.content, new.sender_display_name);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content, sender_display_name)
            VALUES('delete', old.id, old.content, old.sender_display_name);
        END;

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        conn.commit()
    finally:
        conn.close()


def meta_get(key: str) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def meta_set(key: str, value: str):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)
        """, (key, value))
        conn.commit()
    finally:
        conn.close()


def truncate_tables():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM contacts")
        conn.execute("DELETE FROM messages_fts")
        conn.commit()
    finally:
        conn.close()