from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator
from pydantic import ConfigDict, ValidationError, create_model

from approvals import VendorProposal

from database import get_connection, initialize_database
from task_states import TaskStatus, validate_transition
import json
from typing import Literal
from pathlib import Path
from fastapi.responses import FileResponse
@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Company Operator", lifespan=lifespan)


class TaskCreate(BaseModel):
    goal: str = Field(min_length=5, max_length=2000)
    organization_id: str = Field(min_length=1, max_length=100)

    task_type: Literal["general", "inspect_vendor"] = "general"
    target_vendor_id: UUID | None = None

    @model_validator(mode="after")
    def validate_task_target(self):
        if self.task_type == "inspect_vendor":
            if self.target_vendor_id is None:
                raise ValueError(
                    "Inspection tasks require target_vendor_id"
                )
        elif self.target_vendor_id is not None:
            raise ValueError(
                "target_vendor_id is only supported for inspection tasks"
            )

        return self

    goal: str = Field(min_length=5, max_length=2000)
    organization_id: str = Field(min_length=1, max_length=100)
class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]


@app.get("/organizations/{organization_id}/tasks")
def list_organization_tasks(organization_id: str):
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                organization_id,
                goal,
                status,
                task_type,
                target_vendor_id,
                created_at
            FROM tasks
            WHERE organization_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 100
            """,
            (organization_id,),
        ).fetchall()
    finally:
        connection.close()

    return {
        "organization_id": organization_id,
        "tasks": [dict(row) for row in rows],
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    task_id = str(uuid4())
    target_vendor_id = (
        str(task.target_vendor_id)
        if task.target_vendor_id is not None
        else None
    )

    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO tasks (
                id, organization_id, goal, status,
                task_type, target_vendor_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                task.organization_id,
                task.goal,
                "created",
                task.task_type,
                target_vendor_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return {
        "id": task_id,
        "goal": task.goal,
        "organization_id": task.organization_id,
        "status": "created",
        "task_type": task.task_type,
        "target_vendor_id": target_vendor_id,
    }

@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    connection = get_connection()

    try:
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return dict(row)


@app.post("/tasks/{task_id}/queue")
def queue_task(task_id: str):
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )

        current_status = TaskStatus(row["status"])

        if current_status != TaskStatus.CREATED:
            raise HTTPException(
                status_code=409,
                detail="Only newly created tasks can be queued here",
            )

        validate_transition(current_status, TaskStatus.QUEUED)

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.QUEUED.value, task_id),
        )
        connection.commit()

        result = dict(row)
        result["status"] = TaskStatus.QUEUED.value
        return result

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

@app.get("/tasks/{task_id}/events")
def get_task_events(task_id: str):
    connection = get_connection()

    try:
        task = connection.execute(
            "SELECT id FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )

        rows = connection.execute(
            """
            SELECT id, task_id, event_type, message, created_at
            FROM task_events
            WHERE task_id = ?
            ORDER BY id
            """,
            (task_id,),
        ).fetchall()

        return {
            "task_id": task_id,
            "events": [dict(row) for row in rows],
        }

    finally:
        connection.close()
    
@app.get("/approvals/{approval_id}")
def get_approval(approval_id: str):
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT id, task_id, organization_id, action,
                   payload_json, status, created_at, decided_at
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Approval not found",
        )

    result = dict(row)
    result["proposal"] = json.loads(result.pop("payload_json"))

    return result

@app.post("/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
):
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        approval = connection.execute(
            "SELECT * FROM approvals WHERE id = ?",
            (approval_id,),
        ).fetchone()

        if approval is None:
            raise HTTPException(
                status_code=404,
                detail="Approval not found",
            )

        if approval["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail="This approval has already been decided",
            )

        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (approval["task_id"],),
        ).fetchone()

        if task is None:
            raise HTTPException(
                status_code=409,
                detail="The approval's task no longer exists",
            )

        if task["organization_id"] != approval["organization_id"]:
            raise HTTPException(
                status_code=409,
                detail="Approval and task organization do not match",
            )

        current_status = TaskStatus(task["status"])

        if current_status != TaskStatus.WAITING_FOR_APPROVAL:
            raise HTTPException(
                status_code=409,
                detail="Task is not waiting for approval",
            )

        next_status = (
            TaskStatus.QUEUED
            if decision.decision == "approved"
            else TaskStatus.CANCELLED
        )

        validate_transition(current_status, next_status)

        connection.execute(
            """
            UPDATE approvals
            SET status = ?, decided_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (decision.decision, approval_id),
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (next_status.value, task["id"]),
        )

        connection.execute(
            """
            INSERT INTO task_events (task_id, event_type, message)
            VALUES (?, ?, ?)
            """,
            (
                task["id"],
                f"approval_{decision.decision}",
                f"Approval {approval_id}: {decision.decision}",
            ),
        )

        connection.commit()

        return {
            "approval_id": approval_id,
            "status": decision.decision,
            "task_id": task["id"],
            "task_status": next_status.value,
        }

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    
@app.get("/organizations/{organization_id}/vendors/{vendor_id}")
def get_vendor(organization_id: str, vendor_id: str):
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT id, organization_id, legal_name, contact_email,
                   registered_address, service_category, created_at
            FROM vendors
            WHERE id = ? AND organization_id = ?
            """,
            (vendor_id, organization_id),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Vendor not found",
        )

    return dict(row)

@app.get("/portal", include_in_schema=False)
def vendor_portal():
    page = Path(__file__).resolve().parent / "static" / "vendor.html"
    return FileResponse(page)

@app.get("/input-requests/{request_id}")
def get_input_request(request_id: str):
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM input_requests
            WHERE id = ?
            """,
            (request_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Input request not found",
        )

    result = dict(row)
    result["requested_fields"] = json.loads(
        result.pop("requested_fields_json")
    )

    answer_json = result.pop("answer_json")
    result["answer"] = (
        json.loads(answer_json)
        if answer_json is not None
        else None
    )

    return result


class InputAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answers: dict[str, str]


@app.post("/input-requests/{request_id}/answer")
def answer_input_request(request_id: str, body: InputAnswer):
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        request = connection.execute(
            "SELECT * FROM input_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

        if request is None:
            raise HTTPException(
                status_code=404,
                detail="Input request not found",
            )

        if request["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail="This input request has already been answered",
            )

        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (request["task_id"],),
        ).fetchone()

        if (
            task is None
            or task["organization_id"] != request["organization_id"]
            or task["status"] != TaskStatus.WAITING_FOR_INPUT.value
        ):
            raise HTTPException(
                status_code=409,
                detail="Task is not waiting for this input",
            )

        requested_fields = json.loads(
            request["requested_fields_json"]
        )

        if set(body.answers) != set(requested_fields):
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Answer exactly the requested fields",
                    "requested_fields": requested_fields,
                },
            )

        # Reuse the existing vendor field lengths and whitespace rules.
        answer_model = create_model(
            "RequestedVendorAnswers",
            __config__=VendorProposal.model_config,
            **{
                name: (
                    VendorProposal.model_fields[name].annotation,
                    VendorProposal.model_fields[name],
                )
                for name in requested_fields
            },
        )

        try:
            answers = answer_model.model_validate(
                body.answers
            ).model_dump()
        except ValidationError:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Answers must meet the vendor field requirements "
                    "and cannot be blank."
                ),
            ) from None

        checkpoint = connection.execute(
            """
            SELECT history_json
            FROM task_checkpoints
            WHERE task_id = ?
            """,
            (task["id"],),
        ).fetchone()

        if checkpoint is None:
            raise HTTPException(
                status_code=409,
                detail="Agent checkpoint is not ready. Try again shortly.",
            )

        history = json.loads(checkpoint["history_json"])

        # The agent must have saved the request's tool output first.
        last_item = history[-1] if history else {}
        tool_result = {}

        if last_item.get("type") == "function_call_output":
            tool_result = json.loads(last_item["output"])

        if not (
            tool_result.get("ok") is True
            and tool_result.get("tool") == "request_vendor_input"
            and tool_result.get("data", {}).get("request_id")
            == request_id
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Checkpoint does not end with this input request. "
                    "Wait for the worker to finish saving it."
                ),
            )

        history.append({
            "role": "user",
            "content": json.dumps({
                "type": "vendor_input_answer",
                "request_id": request_id,
                "question": request["question"],
                "answers": answers,
                "note": (
                    "These answers supply vendor information. "
                    "They do not approve vendor creation."
                ),
            }),
        })

        validate_transition(
            TaskStatus(task["status"]),
            TaskStatus.QUEUED,
        )

        connection.execute(
            """
            UPDATE input_requests
            SET status = 'answered',
                answer_json = ?,
                answered_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(answers), request_id),
        )

        connection.execute(
            """
            UPDATE task_checkpoints
            SET history_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (json.dumps(history), task["id"]),
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.QUEUED.value, task["id"]),
        )

        connection.execute(
            """
            INSERT INTO task_events (task_id, event_type, message)
            VALUES (?, ?, ?)
            """,
            (
                task["id"],
                "input_answered",
                json.dumps({
                    "request_id": request_id,
                    "answered_fields": requested_fields,
                }),
            ),
        )

        connection.commit()

        return {
            "request_id": request_id,
            "status": "answered",
            "task_id": task["id"],
            "task_status": "queued",
            "answers": answers,
        }

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    page = Path(__file__).resolve().parent / "static" / "dashboard.html"
    return FileResponse(page)

@app.get("/tasks/{task_id}/pending-actions")
def get_pending_actions(task_id: str):
    connection = get_connection()

    try:
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

        if task is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )

        input_rows = connection.execute(
            """
            SELECT id, question, requested_fields_json, created_at
            FROM input_requests
            WHERE task_id = ?
              AND organization_id = ?
              AND status = 'pending'
            ORDER BY created_at, id
            """,
            (task_id, task["organization_id"]),
        ).fetchall()

        approval_rows = connection.execute(
            """
            SELECT id, action, payload_json, created_at
            FROM approvals
            WHERE task_id = ?
              AND organization_id = ?
              AND status = 'pending'
            ORDER BY created_at, id
            """,
            (task_id, task["organization_id"]),
        ).fetchall()

    finally:
        connection.close()

    input_requests = []
    for row in input_rows:
        item = dict(row)
        item["requested_fields"] = json.loads(
            item.pop("requested_fields_json")
        )
        input_requests.append(item)

    approvals = []
    for row in approval_rows:
        item = dict(row)
        item["proposal"] = json.loads(item.pop("payload_json"))
        approvals.append(item)

    return {
        "task_id": task_id,
        "organization_id": task["organization_id"],
        "task_status": task["status"],
        "input_requests": input_requests,
        "approvals": approvals,
    }