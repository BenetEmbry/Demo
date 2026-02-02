from __future__ import annotations

import sqlite3

import pytest

from regression.db_validation import maybe_validate_backend_db


def _create_demo_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE)")
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, total_cents INTEGER NOT NULL, "
            "FOREIGN KEY(user_id) REFERENCES users(id))"
        )

        conn.execute("CREATE INDEX idx_orders_user_id ON orders(user_id)")

        conn.execute("INSERT INTO users(id, username) VALUES (1, 'alice')")
        conn.execute("INSERT INTO users(id, username) VALUES (2, 'bob')")

        conn.execute("INSERT INTO orders(id, user_id, total_cents) VALUES (10, 1, 1000)")
        conn.execute("INSERT INTO orders(id, user_id, total_cents) VALUES (11, 1, 2500)")
        conn.execute("INSERT INTO orders(id, user_id, total_cents) VALUES (12, 2, 500)")

        conn.commit()
    finally:
        conn.close()


def test_sql_basics_and_indexes_via_db_validation_hook(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "demo.db"
    _create_demo_db(str(db_path))

    checks_path = tmp_path / "db_checks.yaml"
    checks_path.write_text(
        """
checks:
  - name: users_count
    query: SELECT COUNT(*) FROM users
    expected: 2

  - name: orders_count
    query: SELECT COUNT(*) FROM orders
    expected: 3

  - name: join_orders_for_alice
    query: |
      SELECT COUNT(*)
      FROM orders o
      JOIN users u ON u.id = o.user_id
      WHERE u.username = 'alice'
    expected: 2

  - name: index_exists
    query: |
      SELECT COUNT(*)
      FROM sqlite_master
      WHERE type='index' AND name='idx_orders_user_id'
    expected: 1
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("DB_MODE", "sqlite")
    monkeypatch.setenv("DB_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("DB_CHECKS_FILE", str(checks_path))

    maybe_validate_backend_db()
