import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from database import get_connection
from task_tools import execute_task_tool
from tools import get_tool_definitions


def run_one_step(task_id: str):
    load_dotenv(Path(__file__).resolve().parent / ".env")

    connection = get_connection()
    try:
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        connection.close()

    if task is None:
        raise ValueError("Task not found")

    if task["status"] != "running":
        raise ValueError("Task must be running")

    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise ValueError("OPENAI_MODEL is missing")

    tool_definitions = [
        {
            "type": "function",
            **definition,
            "strict": True,
        }
        for definition in get_tool_definitions()
    ]

    with OpenAI(timeout=30.0, max_retries=0) as client:
        response = client.responses.create(
            model=model,
            instructions=(
                "You are a company operator beginning a task. "
                "Choose one useful document tool to start gathering "
                "the information needed for the user's goal. "
                "Do not invent file paths. Discover files when necessary. "
                "You cannot create vendor records yet."
            ),
            input=task["goal"],
            tools=tool_definitions,
            tool_choice="required",
            parallel_tool_calls=False,
            max_output_tokens=300,
            store=False,
        )

    if response.status != "completed":
        raise RuntimeError(f"Model response status: {response.status}")

    calls = [
        item for item in response.output
        if item.type == "function_call"
    ]

    if len(calls) != 1:
        raise RuntimeError("Expected exactly one tool call")

    call = calls[0]
    arguments = json.loads(call.arguments)

    print("Selected tool:", call.name)
    print("Arguments:", arguments)

    result = execute_task_tool(task_id, call.name, arguments)

    print("Tool result:")
    print(json.dumps(result, indent=2))

    if response.usage:
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        print("Input tokens:", input_tokens)
        print("Output tokens:", output_tokens)

        if model == "gpt-4.1-mini":
            estimated_cost = (
                input_tokens * 0.40
                + output_tokens * 1.60
            ) / 1_000_000

            print(f"Estimated cost: ${estimated_cost:.8f}")
        else:
            print("Cost estimate unavailable for this model")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python agent_step.py TASK_ID")

    run_one_step(sys.argv[1])