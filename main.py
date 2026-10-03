from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

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