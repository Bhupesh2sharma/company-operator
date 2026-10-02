import json
import sys
from uuid import uuid4

from approvals import VendorProposal
from database import get_connection
from task_states import TaskStatus, validate_transition
from vendor_tools import normalize_legal_name


def execute_vendor_creation(
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

        approval = connection.execute(
            "SELECT * FROM approvals WHERE id = ?",
            (approval_id,),
        ).fetchone()

        if approval is None:
            raise ValueError("Approval not found")

        if (
            approval["task_id"] != task_id
            or approval["organization_id"] != task["organization_id"]
        ):
            raise PermissionError("Approval does not belong to this task")

        if approval["action"] != "create_vendor":
            raise PermissionError("Approval is for a different action")

        if approval["status"] != "approved":
            raise PermissionError("Vendor creation is not approved")

        receipt = connection.execute(
            """
            SELECT * FROM vendor_creation_receipts
            WHERE approval_id = ?
            """,
            (approval_id,),
        ).fetchone()

        if receipt is not None:
            if (
                receipt["task_id"] != task_id
                or receipt["organization_id"] != task["organization_id"]
            ):
                raise PermissionError("Execution receipt does not match")

            connection.commit()

            return {
                "task_id": task_id,
                "vendor_id": receipt["vendor_id"],
                "already_executed": True,
                "task_status": task["status"],
            }

        current_status = TaskStatus(task["status"])

        if current_status != TaskStatus.RUNNING:
            raise ValueError("Task must be running before creation")

        validate_transition(
            current_status,
            TaskStatus.VERIFYING,
        )

        # Read the approved snapshot, not fresh model arguments.
        proposal = VendorProposal.model_validate_json(
            approval["payload_json"]
        )
        name_key = normalize_legal_name(proposal.legal_name)

        existing = connection.execute(
            """
            SELECT id FROM vendors
            WHERE organization_id = ? AND legal_name_key = ?
            """,
            (task["organization_id"], name_key),
        ).fetchone()

        if existing is not None:
            raise ValueError(
                "A matching vendor already exists. "
                "Creation stopped; review the existing record."
            )

        vendor_id = str(uuid4())

        connection.execute(
            """
            INSERT INTO vendors (
                id, organization_id, legal_name, legal_name_key,
                contact_email, registered_address, service_category
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vendor_id,
                task["organization_id"],
                proposal.legal_name,
                name_key,
                proposal.contact_email,
                proposal.registered_address,
                proposal.service_category,
            ),
        )

        connection.execute(
            """
            INSERT INTO vendor_creation_receipts (
                approval_id, task_id, organization_id, vendor_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                approval_id,
                task_id,
                task["organization_id"],
                vendor_id,
            ),
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.VERIFYING.value, task_id),
        )

        connection.execute(
            """
            INSERT INTO task_events (task_id, event_type, message)
            VALUES (?, ?, ?)
            """,
            (
                task_id,
                "vendor_created",
                json.dumps({
                    "approval_id": approval_id,
                    "vendor_id": vendor_id,
                    "next_status": TaskStatus.VERIFYING.value,
                }),
            ),
        )

        connection.commit()

        return {
            "task_id": task_id,
            "vendor_id": vendor_id,
            "already_executed": False,
            "task_status": TaskStatus.VERIFYING.value,
        }

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python vendor_execution.py TASK_ID APPROVAL_ID"
        )

    result = execute_vendor_creation(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))