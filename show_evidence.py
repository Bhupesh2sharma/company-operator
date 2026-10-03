import json
import sys

from checkpoints import load_checkpoint


def main(task_id: str):
    checkpoint = load_checkpoint(task_id)

    if checkpoint is None:
        print("No checkpoint found.")
        return

    found_evidence = False

    for item in checkpoint["history"]:
        if item.get("type") != "function_call_output":
            continue

        result = json.loads(item["output"])

        if (
            result.get("tool") == "inspect_vendor_in_browser"
            and result.get("ok")
        ):
            print("Screenshot:", result["data"]["screenshot_path"])
            found_evidence = True

    if not found_evidence:
        print("No browser screenshot evidence found.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python show_evidence.py TASK_ID")

    main(sys.argv[1])