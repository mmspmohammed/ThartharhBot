import sqlite3
from datetime import datetime
from config import (DB_PATH, DEFAULT_MAX_AGE_DIFF,
                    DEFAULT_MAX_RATING_DIFF, DEFAULT_SAME_COUNTRY)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT, gender TEXT, country TEXT, governorate TEXT,
        birthdate TEXT, zodiac TEXT, lang TEXT DEFAULT 'ar',
        rating REAL DEFAULT 5.0, ratings_count INTEGER DEFAULT 0,
        joined_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS waiting (
        user_id INTEGER PRIMARY KEY, want_gender TEXT, queued_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1 INTEGER, user2 INTEGER, started_at TEXT, ended_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ratings (
        rater_id INTEGER, rated_id INTEGER, stars INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS blocks (
        user_id INTEGER, blocked_id INTEGER,
        PRIMARY KEY (user_id, blocked_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT)""")
    for k, v in (("max_age_diff", str(DEFAULT_MAX_AGE_DIFF)),
                 ("max_rating_diff", str(DEFAULT_MAX_RATING_DIFF)),
                 ("same_country", str(DEFAULT_SAME_COUNTRY))):
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit(); conn.close()

# ---------- users ----------
def ensure_user(user_id, lang="ar"):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (user_id, lang))
    conn.commit(); conn.close()

def get_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row

def save_profile(user_id, data):
    conn = get_db(); c = conn.cursor()
    c.execute("""UPDATE users SET name=?, gender=?, country=?, governorate=?,
                 birthdate=?, zodiac=? WHERE user_id=?""",
              (data["name"], data["gender"], data["country"],
               data["governorate"], data["birthdate"], data["zodiac"], user_id))
    c.execute("UPDATE users SET joined_at=? WHERE user_id=? AND joined_at IS NULL",
              (datetime.now().isoformat(), user_id))
    conn.commit(); conn.close()

def set_lang(user_id, lang):
    conn = get_db()
    conn.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
    conn.commit(); conn.close()

# ---------- settings ----------
def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit(); conn.close()

# ---------- waiting / matching ----------
def add_waiting(user_id, want_gender):
    conn = get_db()
    conn.execute("""INSERT OR REPLACE INTO waiting (user_id, want_gender, queued_at)
                    VALUES (?, ?, ?)""", (user_id, want_gender, datetime.now().isoformat()))
    conn.commit(); conn.close()

def remove_waiting(user_id):
    conn = get_db()
    conn.execute("DELETE FROM waiting WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def get_candidates(my_gender, want_gender):
    """ناس بالطابور: يلي بدوروا على جنسي، وجنسهم هو يلي أنا بدور عليه."""
    conn = get_db()
    rows = conn.execute("""SELECT u.* FROM waiting w JOIN users u ON u.user_id = w.user_id
                           WHERE w.want_gender = ? AND u.gender = ?""",
                        (my_gender, want_gender)).fetchall()
    conn.close()
    return rows

# ---------- chats ----------
def create_chat(user1, user2):
    conn = get_db(); c = conn.cursor()
    c.execute("""INSERT INTO chats (user1, user2, started_at) VALUES (?, ?, ?)""",
              (user1, user2, datetime.now().isoformat()))
    conn.commit()
    cid = c.lastrowid
    conn.close()
    return cid

def get_active_chat(user_id):
    conn = get_db()
    row = conn.execute("""SELECT * FROM chats WHERE ended_at IS NULL
                          AND (user1 = ? OR user2 = ?)
                          ORDER BY id DESC LIMIT 1""", (user_id, user_id)).fetchone()
    conn.close()
    return row

def get_chat(chat_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    conn.close()
    return row

def end_chat(chat_id):
    conn = get_db()
    conn.execute("UPDATE chats SET ended_at=? WHERE id=?", (datetime.now().isoformat(), chat_id))
    conn.commit(); conn.close()

# ---------- ratings / blocks ----------
def add_rating(rater_id, rated_id, stars):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO ratings (rater_id, rated_id, stars) VALUES (?, ?, ?)",
              (rater_id, rated_id, stars))
    c.execute("""UPDATE users SET
                    rating = (SELECT AVG(stars) FROM ratings WHERE rated_id = ?),
                    ratings_count = (SELECT COUNT(*) FROM ratings WHERE rated_id = ?)
                 WHERE user_id = ?""", (rated_id, rated_id, rated_id))
    conn.commit(); conn.close()

def add_block(user_id, blocked_id):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO blocks (user_id, blocked_id) VALUES (?, ?)",
                 (user_id, blocked_id))
    conn.commit(); conn.close()

def is_blocked(a, b):
    conn = get_db()
    row = conn.execute("SELECT 1 FROM blocks WHERE user_id=? AND blocked_id=?", (a, b)).fetchone()
    conn.close()
    return row is not None

# ---------- stats ----------
def stats():
    conn = get_db()
    def one(q):
        return conn.execute(q).fetchone()[0]
    s = {
        "users": one("SELECT COUNT(*) FROM users"),
        "active_chats": one("SELECT COUNT(*) FROM chats WHERE ended_at IS NULL"),
        "waiting": one("SELECT COUNT(*) FROM waiting"),
    }
    conn.close()
    return s
