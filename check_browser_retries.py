from unittest.mock import call, patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from task_tools import dispatch_with_browser_retries


ARGUMENTS = {
    "task_id": "retry-test",
    "organization_id": "demo-company",
    "tool_name": "inspect_vendor_in_browser",
    "arguments": {
        "vendor_id": "174a4000-22ea-4520-8bd3-d5d278191bf6",
    },
}

SUCCESS = {
    "ok": True,
    "tool": "inspect_vendor_in_browser",
    "data": {"found": True},
}


# A timeout followed by success should use two attempts.
with (
    patch("task_tools.dispatch_task_tool") as dispatch,
    patch("task_tools.record_event") as record,
    patch("task_tools.time.sleep") as sleep,
):
    dispatch.side_effect = [
        PlaywrightTimeoutError("Simulated timeout"),
        SUCCESS,
    ]

    result = dispatch_with_browser_retries(**ARGUMENTS)

    assert result == SUCCESS
    assert dispatch.call_count == 2
    sleep.assert_called_once_with(1)
    assert [
        event.args[1] for event in record.call_args_list
    ] == ["tool_retry_scheduled"]

    print("PASS: Timeout recovered on the second attempt.")


# Repeated timeouts must stop after three total attempts.
with (
    patch("task_tools.dispatch_task_tool") as dispatch,
    patch("task_tools.record_event") as record,
    patch("task_tools.time.sleep") as sleep,
):
    dispatch.side_effect = PlaywrightTimeoutError(
        "Simulated persistent timeout"
    )

    try:
        dispatch_with_browser_retries(**ARGUMENTS)
    except PlaywrightTimeoutError:
        pass
    else:
        raise AssertionError("Expected timeout after retry exhaustion")

    assert dispatch.call_count == 3
    assert sleep.call_args_list == [call(1), call(2)]
    assert [
        event.args[1] for event in record.call_args_list
    ] == [
        "tool_retry_scheduled",
        "tool_retry_scheduled",
        "tool_retries_exhausted",
    ]

    print("PASS: Persistent timeout stopped after three attempts.")


# A portal mismatch must propagate immediately.
with (
    patch("task_tools.dispatch_task_tool") as dispatch,
    patch("task_tools.record_event") as record,
    patch("task_tools.time.sleep") as sleep,
):
    dispatch.side_effect = RuntimeError("Wrong vendor displayed")

    try:
        dispatch_with_browser_retries(**ARGUMENTS)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected portal mismatch to propagate")

    dispatch.assert_called_once()
    sleep.assert_not_called()
    record.assert_not_called()

    print("PASS: Portal mismatch was not retried.")


# A successful lookup that finds no vendor is not a timeout.
with (
    patch("task_tools.dispatch_task_tool") as dispatch,
    patch("task_tools.record_event") as record,
    patch("task_tools.time.sleep") as sleep,
):
    dispatch.return_value = {
        "ok": True,
        "tool": "inspect_vendor_in_browser",
        "data": {"found": False},
    }

    result = dispatch_with_browser_retries(**ARGUMENTS)

    assert result["data"]["found"] is False
    dispatch.assert_called_once()
    sleep.assert_not_called()
    record.assert_not_called()

    print("PASS: Missing vendor was not retried.")