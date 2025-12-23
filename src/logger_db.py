import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("logs.db")


def init_db() -> None:
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
        details TEXT,
        tokens_used INTEGER DEFAULT 0
    )
    """
    )

    # Create session stats table
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS session_stats (
        session_id TEXT PRIMARY KEY,
        llm_requests_count INTEGER DEFAULT 0,
        vlm_requests_count INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_update DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    )

    conn.commit()
    conn.close()


def update_session_stats(session_id: str, request_type: str, tokens: int = 0) -> None:
    """
    Update session statistics.

    Args:
        session_id: The session identifier.
        request_type: 'llm' or 'vlm'.
        tokens: Number of tokens used in this request.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Ensure session exists
        cursor.execute(
            "INSERT OR IGNORE INTO session_stats (session_id) VALUES (?)", (session_id,)
        )

        if request_type.lower() == "llm":
            cursor.execute(
                """
                UPDATE session_stats
                SET llm_requests_count = llm_requests_count + 1,
                    total_tokens = total_tokens + ?,
                    last_update = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (tokens, session_id),
            )
        elif request_type.lower() == "vlm":
            cursor.execute(
                """
                UPDATE session_stats
                SET vlm_requests_count = vlm_requests_count + 1,
                    total_tokens = total_tokens + ?,
                    last_update = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (tokens, session_id),
            )

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to update session stats: {e}")


def log_action(
    component: str,
    action_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    session_id: str = "default",
    tokens_used: int = 0,
) -> None:
    """
    Log an action to the database.

    Args:
        component: The part of the system (e.g., 'Orchestrator', 'Planner', 'Browser').
        action_type: The type of action (e.g., 'STEP_START', 'LLM_REQUEST', 'ERROR').
        message: A human-readable message.
        details: A dictionary with extra details (will be stored as JSON).
        session_id: Identifier for the current session/task.
        tokens_used: Number of tokens used (if applicable).
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
