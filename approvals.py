from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from database import get_connection
from task_states import TaskStatus, validate_transition


class VendorProposal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    legal_name: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=320)
    registered_address: str = Field(min_length=1, max_length=1000)
    service_category: str = Field(min_length=1, max_length=200)


def request_vendor_approval(
    task_id: str,
    proposal: VendorProposal,
) -> dict:
    approval_id = str(uuid4())
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

        if current_status != TaskStatus.RUNNING:
            raise ValueError(
                "Task must be running to request vendor approval"
            )

        validate_transition(
            current_status,
            TaskStatus.WAITING_FOR_APPROVAL,
        )

        connection.execute(
            """
            INSERT INTO approvals (
                id, task_id, organization_id,
                action, payload_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                task_id,
                task["organization_id"],
                "create_vendor",
                proposal.model_dump_json(),
                "pending",
            ),
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (
                TaskStatus.WAITING_FOR_APPROVAL.value,
                task_id,
            ),
        )

        connection.execute(
            """
            INSERT INTO task_events (
                task_id, event_type, message
            )
            VALUES (?, ?, ?)
            """,
            (
                task_id,
                "approval_requested",
                f"Vendor creation requires approval: {approval_id}",
            ),
        )

        connection.commit()

        return {
            "approval_id": approval_id,
            "task_id": task_id,
            "status": "pending",
            "action": "create_vendor",
            "proposal": proposal.model_dump(),
        }

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()