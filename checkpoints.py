import json

from database import get_connection


def save_checkpoint(
    task_id: str,
    history: list,
    completed_calls: int,
):
    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO task_checkpoints (
                task_id, history_json, completed_calls
            )
            VALUES (?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                history_json = excluded.history_json,
                completed_calls = excluded.completed_calls,
                updated_at = CURRENT_TIMESTAMP
            """,
            (task_id, json.dumps(history), completed_calls),
        )
        connection.commit()
    finally:
        connection.close()


def load_checkpoint(task_id: str):
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT history_json, completed_calls
            FROM task_checkpoints
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None

    return {
        "history": json.loads(row["history_json"]),
        "completed_calls": row["completed_calls"],
    }