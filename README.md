# Company Operator

A Python prototype that onboards vendors using company documents,
asks for missing information, obtains human approval, creates the
approved record, and verifies the result.

It also inspects existing vendors through a browser portal and
captures screenshot evidence.

## Demonstrated workflows

### Vendor onboarding

1. Read company policy and vendor documents.
2. Search for an existing vendor using normalized exact-name matching.
3. Ask the user for missing information.
4. Save the answer and resume from the checkpoint.
5. Request approval for the exact vendor proposal.
6. Create the approved vendor record.
7. Read back the record and compare it with the approved proposal.
8. Mark the task completed only when verification passes.

### Browser inspection

1. Receive an explicit target vendor ID.
2. Open the local vendor portal using Playwright.
3. Read the displayed record and capture a screenshot.
4. Compare browser observations with the stored vendor.
5. Verify that the screenshot artifact exists.
6. Save the verification result and task status.

## Architecture

- **FastAPI:** task, approval, input-request, and evidence endpoints.
- **SQLite:** tasks, events, checkpoints, vendors, approvals, and receipts.
- **OpenAI Responses API:** model-driven tool selection.
- **Tool executor:** validated arguments and task-scoped organization context.
- **Worker:** queue polling, execution, and explicit checkpoint resume.
- **Playwright:** browser inspection and screenshot capture.
- **Dashboard:** task creation, queuing, answers, approvals, and results.

The model selects tools and gathers information. Application code
enforces state transitions, approval checks, creation receipts,
and verification-based completion.

Vendor creation writes to the prototype's SQLite database.
Browser automation operates the prototype's local vendor portal.

## Requirements

- Tested with Python 3.14 on macOS.
- The worker lock uses `fcntl`, requiring a Unix-like platform.
  Windows requires a different locking implementation.
- An OpenAI API key with API billing enabled for agent execution.
- Chromium installed through Playwright.

Linux has not yet been verified for this project.

## Setup

```bash
git clone https://github.com/Bhupesh2sharma/company-operator.git
cd company-operator

python3.14 -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env
```

Edit `.env` and enter your own API key:

```dotenv
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-mini
```

Never commit `.env`.

Initialize the database:

```bash
python -c "from database import initialize_database; initialize_database()"
```

## Run

In terminal 1:

```bash
source .venv/bin/activate
python -m uvicorn main:app --reload
```

In terminal 2:

```bash
source .venv/bin/activate
python run_worker.py --watch --max-model-calls 8
```

Open:

- Dashboard: http://127.0.0.1:8000/dashboard
- API documentation: http://127.0.0.1:8000/docs
- Vendor portal: http://127.0.0.1:8000/portal

Open the dashboard through HTTP, not directly as a local HTML file.

The worker processes one task at a time. Empty queue polling does
not call OpenAI. Press Ctrl+C while idle to stop it.

## Demo: missing information to verified creation

Use a fresh database or a vendor that has not already been onboarded.

1. Open the dashboard and set the organization to `demo-company`.
2. Select `Vendor onboarding / general`.
3. Enter this goal:

   > Onboard Maple Demo Services LLP using
   > vendors/maple-demo/profile.json and policies/vendor_onboarding.md.
   > Check duplicates, ask me for missing information, and obtain
   > approval before creation.

4. Create and queue the task.
5. Refresh after the worker pauses for input.
6. Select **Review required action** and provide `maple@example.com`.
7. Refresh when the task is waiting for approval.
8. Review the complete proposal and approve creation.
9. Refresh after execution and open **View result and evidence**.

The task should complete with matching expected and actual vendor fields.

Answering a question does not approve vendor creation.

## Demo: browser inspection

After onboarding a vendor:

1. Copy its vendor ID from the completed verification report.
2. Create an `Inspect an existing vendor` task.
3. Enter that ID and this goal:

   > Inspect this vendor and return its displayed details and
   > screenshot evidence.

4. Queue the task.
5. Open its result after execution.

The dashboard displays verification checks and the saved screenshot.
Vendor IDs are generated locally; IDs from another installation
will not work.

## Tests

These checks do not require OpenAI calls:

```bash
python -m unittest -v test_vendor_workflow
python check_inspection_guard.py
python check_browser_retries.py
```

The vendor workflow tests use temporary databases. They cover:

- Missing, pending, and rejected approvals.
- Approval ownership across tasks and organizations.
- Repeated execution without duplicate creation.
- Duplicate vendor prevention.
- Successful verification.
- Verification failure after changed or missing vendor records.

The guard and retry scripts use mocks. They do not demonstrate a
real browser outage recovering.

## Checkpoint resume

Process one queued task with a limited call allowance:

```bash
python run_worker.py --max-model-calls 1
```

After it pauses, resume its task ID:

```bash
python run_worker.py --resume TASK_ID --max-model-calls 8
```

The limit includes model calls already recorded in the checkpoint.
It is not an additional allowance.

Stop a watch-mode worker before using a separate resume command.
Both commands acquire the same local worker lock.

Only `running` or `verifying` tasks can be explicitly resumed.
Answering a question or approving a proposal queues the task
through the corresponding API endpoint.

## Reliability controls

- Explicit task-state transitions.
- Approved snapshots used for vendor creation.
- Atomic vendor creation, receipt recording, and status update.
- Repeated creation calls return the existing execution receipt.
- Inspection tools restricted to the task's exact vendor ID.
- Company-scoped file access and vendor queries.
- Persistent conversation checkpoints and audit events.
- Up to three attempts per browser-tool invocation for Playwright
  timeout exceptions, with bounded waits.
- Separate verification before completion.

## Current limitations

- Local prototype with no authentication or reviewer identity tracking.
  Organization filtering is not a complete tenant security boundary.
- No external enterprise integration or desktop application automation.
- Company context is stored in files; there is no feedback-learning system.
- Duplicate search uses normalized exact names, not fuzzy matching.
- Policy compliance during planning is partly prompt-driven.
- Browser inspection uses fixed selectors for the local portal.
- Screenshot checks verify file presence and PNG signature, not pixels.
- Checkpoints are not atomic with every tool action; some crash windows
  still require manual recovery.
- Browser retries are per invocation, not a persisted task-wide budget.
- Model-call limits do not provide a hard monetary spending cap.
- Some paused or errored tasks remain `running` until explicitly resumed.
- No distributed workers, worker leases, or calendar-based scheduling.
- Dashboard updates require manual refresh.
- Automated API and full browser workflow coverage is incomplete.

The prototype demonstrates a narrow working operator rather than
a production-ready general-purpose AI employee.