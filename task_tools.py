import json

from database import get_connection
from task_states import TaskStatus
from tools import execute_tool
from pydantic import ValidationError

from approvals import VendorProposal, request_vendor_approval

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

def dispatch_task_tool(
    task_id: str,
    organization_id: str,
    tool_name: str,
    arguments: dict,
) -> dict:
    if tool_name != "request_vendor_approval":
        return execute_tool(
            tool_name,
            arguments,
            organization_id=organization_id,
        )

    try:
        proposal = VendorProposal.model_validate(arguments)

        result = request_vendor_approval(
            task_id=task_id,
            proposal=proposal,
        )

        return {
            "ok": True,
            "tool": tool_name,
            "data": result,
        }

    except ValidationError:
        return {
            "ok": False,
            "tool": tool_name,
            "error": {
                "type": "invalid_arguments",
                "message": (
                    "Provide all four vendor fields as nonempty strings. "
                    "Extra fields are not allowed."
                ),
            },
        }

    except ValueError as error:
        return {
            "ok": False,
            "tool": tool_name,
            "error": {
                "type": "approval_request_rejected",
                "message": str(error),
            },
        }

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
            result = dispatch_task_tool(
            task_id=task_id,
            organization_id=task["organization_id"],
            tool_name=tool_name,
            arguments=arguments,
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