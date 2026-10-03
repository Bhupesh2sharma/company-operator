from typing import Literal
from uuid import uuid4
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import get_connection
from task_states import TaskStatus, validate_transition


VendorField = Literal[
    "legal_name",
    "contact_email",
    "registered_address",
    "service_category",
]


class InputRequestArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    question: str = Field(min_length=5, max_length=2000)
    requested_fields: list[VendorField] = Field(
        min_length=1,
        max_length=4,
    )

    @field_validator("requested_fields")
    @classmethod
    def reject_duplicate_fields(cls, fields):
        if len(fields) != len(set(fields)):
            raise ValueError("Requested fields must be unique")
        return fields


def request_vendor_input(
    task_id: str,
    request: InputRequestArguments,
) -> dict:
    request_id = str(uuid4())
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Task not found")

        if task["task_type"] == "inspect_vendor":
            raise ValueError(
                "Vendor inspection tasks cannot request onboarding input"
            )

        current_status = TaskStatus(task["status"])

        if current_status != TaskStatus.RUNNING:
            raise ValueError(
                "Task must be running to request input"
            )

        pending = connection.execute(
            """
            SELECT id
            FROM input_requests
            WHERE task_id = ? AND status = 'pending'
            """,
            (task_id,),
        ).fetchone()

        if pending is not None:
            raise ValueError("Task already has a pending input request")

        validate_transition(
            current_status,
            TaskStatus.WAITING_FOR_INPUT,
        )

        connection.execute(
            """
            INSERT INTO input_requests (
                id,
                task_id,
                organization_id,
                question,
                requested_fields_json,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                task_id,
                task["organization_id"],
                request.question,
                json.dumps(request.requested_fields),
                "pending",
            ),
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.WAITING_FOR_INPUT.value, task_id),
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
                "input_requested",
                json.dumps({
                    "request_id": request_id,
                    "question": request.question,
                    "requested_fields": request.requested_fields,
                }),
            ),
        )

        connection.commit()

        return {
            "request_id": request_id,
            "task_id": task_id,
            "status": "pending",
            "question": request.question,
            "requested_fields": request.requested_fields,
            "task_status": TaskStatus.WAITING_FOR_INPUT.value,
        }

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()