"""Small persistent account store for first-login registration."""
from contextlib import closing
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import threading

ITERATIONS = 600_000


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)


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
        with self.lock, closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT salt, password_hash FROM accounts '
                             'WHERE username = ?', (username,)).fetchone()
        if row:
            self._verify(password, row)
            return False

        salt = os.urandom(16)
        digest = _hash_password(password, salt)
        with self.lock, closing(sqlite3.connect(self.path)) as db:
            # Another login/store may have registered this name while we hashed.
            inserted = db.execute(
                'INSERT INTO accounts VALUES (?, ?, ?) '
                'ON CONFLICT(username) DO NOTHING', (username, salt, digest)
            ).rowcount
            db.commit()
            if inserted:
                return True
            row = db.execute('SELECT salt, password_hash FROM accounts '
                             'WHERE username = ?', (username,)).fetchone()
        self._verify(password, row)
        return False

    @staticmethod
    def _verify(password, row):
        if not row or not hmac.compare_digest(_hash_password(password, row[0]), row[1]):
            raise ValueError('Incorrect username or password')
