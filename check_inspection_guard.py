from unittest.mock import MagicMock, patch

from task_tools import execute_task_tool


TARGET_VENDOR_ID = "174a4000-22ea-4520-8bd3-d5d278191bf6"

task = {
    "id": "guard-test",
    "organization_id": "demo-company",
    "status": "running",
    "task_type": "inspect_vendor",
    "target_vendor_id": TARGET_VENDOR_ID,
}

connection = MagicMock()
connection.execute.return_value.fetchone.return_value = task

with (
    patch("task_tools.get_connection", return_value=connection),
    patch("task_tools.record_event"),
    patch("task_tools.dispatch_task_tool") as dispatch,
):
    # An inspection task cannot request vendor creation.
    result = execute_task_tool(
        task["id"],
        "request_vendor_approval",
        {},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "permission_denied"
    dispatch.assert_not_called()
    print("PASS: Creation approval tool blocked.")

    # It cannot inspect a different vendor.
    result = execute_task_tool(
        task["id"],
        "inspect_vendor_in_browser",
        {"vendor_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "permission_denied"
    dispatch.assert_not_called()
    print("PASS: Different vendor ID blocked.")

    # The exact target is allowed through to the dispatcher.
    dispatch.return_value = {
        "ok": True,
        "tool": "inspect_vendor_in_browser",
        "data": {},
    }

    result = execute_task_tool(
        task["id"],
        "inspect_vendor_in_browser",
        {"vendor_id": TARGET_VENDOR_ID},
    )

    assert result["ok"] is True
    dispatch.assert_called_once_with(
        task_id=task["id"],
        organization_id="demo-company",
        tool_name="inspect_vendor_in_browser",
        arguments={"vendor_id": TARGET_VENDOR_ID},
    )
    print("PASS: Exact target allowed with the task's organization.")