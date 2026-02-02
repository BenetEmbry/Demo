from __future__ import annotations

import sqlite3


def test_transactions_commit_and_rollback() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")

        # Rollback path
        conn.execute("BEGIN")
        conn.execute("INSERT INTO ledger(id, note) VALUES (1, 'temp')")
        conn.rollback()

        cur = conn.execute("SELECT COUNT(*) FROM ledger")
        assert cur.fetchone()[0] == 0

        # Commit path
        conn.execute("BEGIN")
        conn.execute("INSERT INTO ledger(id, note) VALUES (2, 'committed')")
        conn.commit()

        cur = conn.execute("SELECT COUNT(*) FROM ledger")
        assert cur.fetchone()[0] == 1

    finally:
        conn.close()


def test_transaction_atomicity_all_or_nothing() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")

        try:
            conn.execute("BEGIN")
            conn.execute("INSERT INTO accounts(id, name) VALUES (1, 'a')")
            # This will violate UNIQUE(name)
            conn.execute("INSERT INTO accounts(id, name) VALUES (2, 'a')")
            conn.commit()
        except Exception:
            conn.rollback()

        cur = conn.execute("SELECT COUNT(*) FROM accounts")
        assert cur.fetchone()[0] == 0

    finally:
        conn.close()
