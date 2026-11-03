"""Small persistent account store for first-login registration."""
from contextlib import closing
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import threading

ITERATIONS = 600_000


class Accounts:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS accounts ('
                       'username TEXT PRIMARY KEY, salt BLOB NOT NULL, '
                       'password_hash BLOB NOT NULL)')
            db.commit()

    def authenticate(self, username, password):
        if not isinstance(password, str) or not 6 <= len(password) <= 128:
            raise ValueError('Password must contain 6-128 characters')
        # Serialize first registration so two logins cannot claim one name.
        with self.lock, closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT salt, password_hash FROM accounts '
                             'WHERE username = ?', (username,)).fetchone()
            salt = row[0] if row else os.urandom(16)
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
            if row:
                if not hmac.compare_digest(digest, row[1]):
                    raise ValueError('Incorrect username or password')
                return False
            db.execute('INSERT INTO accounts VALUES (?, ?, ?)',
                       (username, salt, digest))
            db.commit()
            return True
