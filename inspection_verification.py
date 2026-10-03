import json
import sys
from pathlib import Path

from checkpoints import load_checkpoint
from database import get_connection
from task_states import TaskStatus, validate_transition

EVIDENCE_ROOT = (Path(__file__).resolve().parent / "evidence").resolve()

VENDOR_FIELDS = (
    "legal_name",
    "contact_email",
    "registered_address",
    "service_category",
)


def verify_inspection(task_id: str) -> dict:
    connection = get_connection()

    try:
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Task not found")

        if task["task_type"] != "inspect_vendor":
            raise ValueError("Task is not a vendor inspection")

        if not task["target_vendor_id"]:
            raise ValueError("Task has no target vendor")

        vendor = connection.execute(
            """
            SELECT * FROM vendors
            WHERE organization_id = ? AND id = ?
            """,
            (task["organization_id"], task["target_vendor_id"]),
        ).fetchone()
    finally:
        connection.close()

    checkpoint = load_checkpoint(task_id)

    if checkpoint is None:
        raise ValueError("No saved inspection history")

    history = checkpoint["history"]

    # Associate tool outputs with the actual saved tool calls.
    inspection_calls = {}

    for item in history:
        if (
            item.get("type") == "function_call"
            and item.get("name") == "inspect_vendor_in_browser"
        ):
            arguments = json.loads(item["arguments"])

            if arguments.get("vendor_id") == task["target_vendor_id"]:
                inspection_calls[item["call_id"]] = arguments

    # Use the latest matching inspection output.
    result = None

    for item in history:
        if (
            item.get("type") == "function_call_output"
            and item.get("call_id") in inspection_calls
        ):
            result = json.loads(item["output"])

    if result is None:
        raise ValueError("No tool output for the requested vendor")

    if (
        result.get("ok") is not True
        or result.get("tool") != "inspect_vendor_in_browser"
    ):
        raise ValueError("The saved browser inspection did not succeed")

    data = result.get("data", {})
    observed = data.get("observed") or {}

    screenshot_value = data.get("screenshot_path")
    screenshot = (
        Path(screenshot_value).resolve()
        if isinstance(screenshot_value, str) and screenshot_value
        else None
    )

    screenshot_valid = False

    if (
        screenshot is not None
        and screenshot.is_relative_to(EVIDENCE_ROOT)
        and screenshot.is_file()
    ):
        with screenshot.open("rb") as image:
            screenshot_valid = image.read(8) == b"\x89PNG\r\n\x1a\n"

    checks = {
        "vendor_found": data.get("found") is True,
        "result_organization_matches": (
            data.get("organization_id") == task["organization_id"]
        ),
        "result_vendor_matches": (
            data.get("vendor_id") == task["target_vendor_id"]
        ),
        "displayed_organization_matches": (
            observed.get("organization_id") == task["organization_id"]
        ),
        "displayed_vendor_matches": (
            observed.get("id") == task["target_vendor_id"]
        ),
        "saved_vendor_exists": vendor is not None,
        "screenshot_present_with_png_signature": screenshot_valid,
    }

    for field in VENDOR_FIELDS:
        checks[f"{field}_matches"] = (
            vendor is not None
            and field in observed
            and observed[field] == vendor[field]
        )

    return {
        "task_id": task_id,
        "vendor_id": task["target_vendor_id"],
        "passed": all(checks.values()),
        "checks": checks,
        "observed": observed,
        "screenshot_path": str(screenshot) if screenshot else None,
        "task_status": task["status"],
    }



def complete_inspection(task_id: str) -> dict:
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Task not found")

        if task["task_type"] != "inspect_vendor":
            raise ValueError("Task is not a vendor inspection")

        current_status = TaskStatus(task["status"])

        if current_status not in (
            TaskStatus.RUNNING,
            TaskStatus.VERIFYING,
        ):
            raise ValueError(
                "Inspection must be running or verifying"
            )

        # Recheck evidence before changing the task status.
        report = verify_inspection(task_id)

        if current_status == TaskStatus.RUNNING:
            validate_transition(
                current_status,
                TaskStatus.VERIFYING,
            )

            connection.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                (TaskStatus.VERIFYING.value, task_id),
            )

            connection.execute(
                """
                INSERT INTO task_events
                    (task_id, event_type, message)
                VALUES (?, ?, ?)
                """,
                (
                    task_id,
                    "inspection_verification_started",
                    "Checking browser observations and screenshot evidence",
                ),
            )

        next_status = (
            TaskStatus.COMPLETED
            if report["passed"]
            else TaskStatus.FAILED
        )

        validate_transition(
            TaskStatus.VERIFYING,
            next_status,
        )

        report["task_status"] = next_status.value

        connection.execute(
            """
            INSERT INTO task_events
                (task_id, event_type, message)
            VALUES (?, ?, ?)
            """,
            (
                task_id,
                (
                    "inspection_verification_passed"
                    if report["passed"]
                    else "inspection_verification_failed"
                ),
                json.dumps(report),
            ),
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (next_status.value, task_id),
        )

        connection.commit()
        return report

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python inspection_verification.py TASK_ID"
        )

    print(json.dumps(complete_inspection(sys.argv[1]), indent=2))