import sqlite3
import json
import datetime
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path("logs.db")


def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create logs table
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        session_id TEXT,
        component TEXT,
        action_type TEXT,
        message TEXT,
        details TEXT
    )
    """
    )

    conn.commit()
    conn.close()


def log_action(
    component: str,
    action_type: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
    session_id: str = "default",
):
    """
    Log an action to the database.

    Args:
        component: The part of the system (e.g., 'Orchestrator', 'Planner', 'Browser').
        action_type: The type of action (e.g., 'STEP_START', 'LLM_REQUEST', 'ERROR').
        message: A human-readable message.
        details: A dictionary with extra details (will be stored as JSON).
        session_id: Identifier for the current session/task.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        details_json = json.dumps(details, ensure_ascii=False) if details else None

        cursor.execute(
            """
        INSERT INTO action_logs (component, action_type, message, details, session_id)
        VALUES (?, ?, ?, ?, ?)
        """,
            (component, action_type, message, details_json, session_id),
        )

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to write to DB log: {e}")


# Initialize DB on module import (or you can call it explicitly)
init_db()
