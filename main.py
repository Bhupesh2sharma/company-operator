from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from database import get_connection, initialize_database
from task_states import TaskStatus, validate_transition


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Company Operator", lifespan=lifespan)


class TaskCreate(BaseModel):
    goal: str = Field(min_length=5, max_length=2000)
    organization_id: str = Field(min_length=1, max_length=100)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    task_id = str(uuid4())
    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO tasks (id, organization_id, goal, status)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, task.organization_id, task.goal, "created"),
        )
        connection.commit()
    finally:
        connection.close()

    return {
        "id": task_id,
        "goal": task.goal,
        "organization_id": task.organization_id,
        "status": "created",
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