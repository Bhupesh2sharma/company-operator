from database import get_connection
from task_states import TaskStatus, validate_transition
from worker_lock import worker_lock

def claim_next_task():
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            """
            SELECT * FROM tasks
            WHERE status = ?
            ORDER BY created_at, id
            LIMIT 1
            """,
            (TaskStatus.QUEUED.value,),
        ).fetchone()

        if row is None:
            connection.commit()
            return None

        validate_transition(
            TaskStatus(row["status"]),
            TaskStatus.RUNNING,
        )

        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.RUNNING.value, row["id"]),
        )
        connection.execute(
            """
            INSERT INTO task_events (task_id, event_type, message)
            VALUES (?, ?, ?)
            """,
            (
                row["id"],
                "task_claimed",
                "Worker claimed the task: queued -> running",
            ),
        )
        connection.commit()

        task = dict(row)
        task["status"] = TaskStatus.RUNNING.value
        return task

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    with worker_lock():
        task = claim_next_task()

        if task is None:
            print("No queued tasks available")
        else:
            print(f"Claimed task: {task['id']}")
            print(f"Goal: {task['goal']}")
            print(f"Status: {task['status']}")