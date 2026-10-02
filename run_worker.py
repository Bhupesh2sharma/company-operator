import json

from agent_loop import run_agent
from database import get_connection, initialize_database
from task_tools import record_event
from vendor_execution import execute_vendor_creation
from verification import verify_vendor_creation
from worker import claim_next_task


def find_approved_creation(task_id: str):
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT id
            FROM approvals
            WHERE task_id = ?
              AND action = 'create_vendor'
              AND status = 'approved'
            ORDER BY created_at, id
            """,
            (task_id,),
        ).fetchall()
    finally:
        connection.close()

    if len(rows) > 1:
        raise ValueError(
            "Multiple approved creations found. "
            "An explicit execution choice is required."
        )

    return rows[0]["id"] if rows else None


def run_once():
    initialize_database()

    task = claim_next_task()

    if task is None:
        print("No queued tasks available")
        return

    task_id = task["id"]
    print("Claimed task:", task_id)
    print("Goal:", task["goal"])

    try:
        approval_id = find_approved_creation(task_id)

        if approval_id is None:
            print("\nStarting information gathering")
            run_agent(task_id)
            print(
                "\nAssessment stage returned. "
                "Check task history for the outcome."
            )
            return

        print("\nExecuting the approved vendor creation")
        creation = execute_vendor_creation(task_id, approval_id)
        print(json.dumps(creation, indent=2))

        print("\nVerifying the saved vendor")
        evidence = verify_vendor_creation(task_id, approval_id)
        print(json.dumps(evidence, indent=2))

    except Exception as error:
        record_event(
            task_id,
            "worker_error",
            json.dumps({
                "error_type": type(error).__name__,
                "message": str(error),
            }),
        )
        raise


if __name__ == "__main__":
    run_once()