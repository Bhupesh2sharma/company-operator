import json
import sys

from database import get_connection
from task_states import TaskStatus, validate_transition


VENDOR_FIELDS = (
    "legal_name",
    "contact_email",
    "registered_address",
    "service_category",
)


def verify_vendor_creation(
    task_id: str,
    approval_id: str,
) -> dict:
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Task not found")

        current_status = TaskStatus(task["status"])

        if current_status != TaskStatus.VERIFYING:
            raise ValueError("Task must be verifying")

        approval = connection.execute(
            "SELECT * FROM approvals WHERE id = ?",
            (approval_id,),
        ).fetchone()

        if approval is None:
            raise ValueError("Approval not found")

        if (
            approval["task_id"] != task_id
            or approval["organization_id"] != task["organization_id"]
            or approval["action"] != "create_vendor"
            or approval["status"] != "approved"
        ):
            raise PermissionError("No matching approved action")

        receipt = connection.execute(
            """
            SELECT * FROM vendor_creation_receipts
            WHERE approval_id = ?
              AND task_id = ?
              AND organization_id = ?
            """,
            (approval_id, task_id, task["organization_id"]),
        ).fetchone()

        if receipt is None:
            raise ValueError("Matching execution receipt not found")

        vendor = connection.execute(
            """
            SELECT * FROM vendors
            WHERE id = ? AND organization_id = ?
            """,
            (receipt["vendor_id"], task["organization_id"]),
        ).fetchone()

        expected = json.loads(approval["payload_json"])

        if any(field not in expected for field in VENDOR_FIELDS):
            raise ValueError("Approved snapshot is missing required fields")

        checks = {
            field: {
                "expected": expected[field],
                "actual": vendor[field] if vendor is not None else None,
                "matches": (
                    vendor is not None
                    and vendor[field] == expected[field]
                ),
            }
            for field in VENDOR_FIELDS
        }

        passed = (
            vendor is not None
            and all(check["matches"] for check in checks.values())
        )

        next_status = (
            TaskStatus.COMPLETED
            if passed
            else TaskStatus.FAILED
        )

        validate_transition(current_status, next_status)

        evidence = {
            "task_id": task_id,
            "approval_id": approval_id,
            "vendor_id": receipt["vendor_id"],
            "vendor_found": vendor is not None,
            "passed": passed,
            "checks": checks,
            "task_status": next_status.value,
        }

        connection.execute(
            """
            INSERT INTO task_events (task_id, event_type, message)
            VALUES (?, ?, ?)
            """,
            (
                task_id,
                "verification_passed" if passed else "verification_failed",
                json.dumps(evidence),
            ),
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (next_status.value, task_id),
        )

        connection.commit()
        return evidence

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python verification.py TASK_ID APPROVAL_ID"
        )

    result = verify_vendor_creation(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))