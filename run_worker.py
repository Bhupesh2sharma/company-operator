import argparse
import json

from agent_loop import MAX_MODEL_CALLS, run_agent
from checkpoints import load_checkpoint
from database import get_connection, initialize_database
from inspection_verification import complete_inspection
from task_tools import record_event
from vendor_execution import execute_vendor_creation
from verification import verify_vendor_creation
from worker import claim_next_task
from worker_lock import worker_lock


def get_task(task_id: str) -> dict:
    connection = get_connection()

    try:
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise ValueError("Task not found")

    return dict(row)


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


def has_saved_assessment(task_id: str) -> bool:
    checkpoint = load_checkpoint(task_id)

    if checkpoint is None or not checkpoint["history"]:
        return False

    last_item = checkpoint["history"][-1]

    return (
        last_item.get("type") == "message"
        and last_item.get("role") == "assistant"
    )


def process_task(task: dict, max_model_calls: int):
    task_id = task["id"]

    print("Task:", task_id)
    print("Goal:", task["goal"])
    print("Status:", task["status"])

    try:
        if task["task_type"] == "inspect_vendor":
            if task["status"] == "running":
                print("\nStarting or resuming browser inspection")
                run_agent(
                    task_id,
                    max_model_calls=max_model_calls,
                )

                if not has_saved_assessment(task_id):
                    print(
                        "\nInspection paused without a final assessment. "
                        "Task remains unfinished."
                    )
                    return

            print("\nVerifying browser inspection evidence")
            evidence = complete_inspection(task_id)
            print(json.dumps(evidence, indent=2))
            return

        approval_id = find_approved_creation(task_id)

        if task["status"] == "verifying":
            if approval_id is None:
                raise ValueError(
                    "Cannot verify creation without an approved proposal"
                )

            print("\nResuming verification of the saved vendor")
            evidence = verify_vendor_creation(task_id, approval_id)
            print(json.dumps(evidence, indent=2))
            return

        if approval_id is None:
            print("\nStarting or resuming information gathering")
            run_agent(
                task_id,
                max_model_calls=max_model_calls,
            )

            current_task = get_task(task_id)
            print("\nAgent stage returned.")
            print("Current task status:", current_task["status"])
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


def run_once(max_model_calls: int = MAX_MODEL_CALLS):
    with worker_lock():
        initialize_database()
        task = claim_next_task()

        if task is None:
            print("No queued tasks available")
            return

        print("Claimed task:", task["id"])
        process_task(task, max_model_calls)


def resume_task(
    task_id: str,
    max_model_calls: int = MAX_MODEL_CALLS,
):
    with worker_lock():
        initialize_database()
        task = get_task(task_id)

        if task["status"] not in ("running", "verifying"):
            raise ValueError(
                "Only running or verifying tasks can be resumed. "
                f"Current status: {task['status']}"
            )

        record_event(
            task_id,
            "task_resume_requested",
            json.dumps({
                "status": task["status"],
                "max_model_calls": max_model_calls,
            }),
        )

        print("Resuming task:", task_id)
        process_task(task, max_model_calls)


def main():
    parser = argparse.ArgumentParser(
        description="Run one queued task or resume interrupted work."
    )

    parser.add_argument(
        "--resume",
        metavar="TASK_ID",
        help="Resume a running or verifying task.",
    )

    parser.add_argument(
        "--max-model-calls",
        type=int,
        choices=range(1, 11),
        default=MAX_MODEL_CALLS,
        metavar="1-10",
        help="Total model-call allowance, including saved calls.",
    )

    args = parser.parse_args()

    if args.resume:
        resume_task(args.resume, args.max_model_calls)
    else:
        run_once(args.max_model_calls)


if __name__ == "__main__":
    main()