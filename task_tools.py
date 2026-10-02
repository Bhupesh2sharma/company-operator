import json

from database import get_connection
from task_states import TaskStatus
from tools import execute_tool


def record_event(task_id: str, event_type: str, message: str):
    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO task_events (task_id, event_type, message)
            VALUES (?, ?, ?)
            """,
            (task_id, event_type, message),
        )
        connection.commit()
    finally:
        connection.close()


def execute_task_tool(
    task_id: str,
    tool_name: str,
    arguments: dict,
) -> dict:
    connection = get_connection()

    try:
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        connection.close()

    if task is None:
        raise ValueError("Task not found")

    if task["status"] != TaskStatus.RUNNING.value:
        raise ValueError("Task must be running to execute tools")

    record_event(
        task_id,
        "tool_started",
        json.dumps({"tool": tool_name, "arguments": arguments}),
    )

    try:
        result = execute_tool(
            tool_name,
            arguments,
            organization_id=task["organization_id"],
        )
    except Exception:
        record_event(
            task_id,
            "tool_failed",
            json.dumps({
                "tool": tool_name,
                "error": "Unexpected execution error",
            }),
        )
        raise

    event_type = "tool_succeeded" if result["ok"] else "tool_failed"

    summary = {"tool": tool_name, "ok": result["ok"]}
    if not result["ok"]:
        summary["error"] = result["error"]

    record_event(task_id, event_type, json.dumps(summary))

    return result