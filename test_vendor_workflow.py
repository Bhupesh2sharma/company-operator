import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import database
from vendor_execution import execute_vendor_creation
from verification import verify_vendor_creation


class VendorWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)

        temporary_database = (
            Path(temporary_directory.name) / "test_operator.db"
        )

        database_patch = patch.object(
            database,
            "DATABASE_PATH",
            temporary_database,
        )
        database_patch.start()
        self.addCleanup(database_patch.stop)

        database.initialize_database()

        self.proposal = {
            "legal_name": "Integration Test Vendor LLP",
            "contact_email": "vendor@example.com",
            "registered_address": "10 Test Road, Demo City",
            "service_category": "Office supplies",
        }

    def execute_sql(self, sql, parameters=()):
        with closing(database.get_connection()) as connection:
            connection.execute(sql, parameters)
            connection.commit()

    def fetch_one(self, sql, parameters=()):
        with closing(database.get_connection()) as connection:
            return connection.execute(sql, parameters).fetchone()

    def create_task(self, organization_id="test-company"):
        task_id = str(uuid4())

        self.execute_sql(
            """
            INSERT INTO tasks (
                id, organization_id, goal, status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                task_id,
                organization_id,
                "Onboard the integration test vendor",
                "running",
            ),
        )

        return task_id

    def create_approval(
        self,
        task_id,
        status="approved",
        organization_id="test-company",
    ):
        approval_id = str(uuid4())

        self.execute_sql(
            """
            INSERT INTO approvals (
                id, task_id, organization_id,
                action, payload_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                task_id,
                organization_id,
                "create_vendor",
                json.dumps(self.proposal),
                status,
            ),
        )

        return approval_id

    def assert_task_status(self, task_id, expected):
        row = self.fetch_one(
            "SELECT status FROM tasks WHERE id = ?",
            (task_id,),
        )
        self.assertEqual(row["status"], expected)

    def assert_no_creation(self):
        vendors = self.fetch_one(
            "SELECT COUNT(*) AS total FROM vendors"
        )
        receipts = self.fetch_one(
            "SELECT COUNT(*) AS total FROM vendor_creation_receipts"
        )
        events = self.fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM task_events
            WHERE event_type = 'vendor_created'
            """
        )

        self.assertEqual(vendors["total"], 0)
        self.assertEqual(receipts["total"], 0)
        self.assertEqual(events["total"], 0)

    def test_missing_approval_blocks_creation(self):
        task_id = self.create_task()

        with self.assertRaisesRegex(ValueError, "Approval not found"):
            execute_vendor_creation(task_id, str(uuid4()))

        self.assert_no_creation()
        self.assert_task_status(task_id, "running")

    def test_pending_and_rejected_approvals_block_creation(self):
        for status in ("pending", "rejected"):
            with self.subTest(status=status):
                task_id = self.create_task()
                approval_id = self.create_approval(task_id, status=status)

                with self.assertRaisesRegex(
                    PermissionError,
                    "not approved",
                ):
                    execute_vendor_creation(task_id, approval_id)

                self.assert_no_creation()
                self.assert_task_status(task_id, "running")

    def test_other_tasks_approval_is_rejected(self):
        owner_task = self.create_task()
        other_task = self.create_task()
        approval_id = self.create_approval(owner_task)

        with self.assertRaisesRegex(
            PermissionError,
            "does not belong",
        ):
            execute_vendor_creation(other_task, approval_id)

        self.assert_no_creation()
        self.assert_task_status(other_task, "running")

    def test_other_organizations_approval_is_rejected(self):
        task_id = self.create_task()
        approval_id = self.create_approval(
            task_id,
            organization_id="other-company",
        )

        with self.assertRaisesRegex(
            PermissionError,
            "does not belong",
        ):
            execute_vendor_creation(task_id, approval_id)

        self.assert_no_creation()
        self.assert_task_status(task_id, "running")

    def test_repeat_execution_creates_only_one_vendor(self):
        task_id = self.create_task()
        approval_id = self.create_approval(task_id)

        first = execute_vendor_creation(task_id, approval_id)
        second = execute_vendor_creation(task_id, approval_id)

        self.assertFalse(first["already_executed"])
        self.assertTrue(second["already_executed"])
        self.assertEqual(first["vendor_id"], second["vendor_id"])

        vendors = self.fetch_one(
            "SELECT COUNT(*) AS total FROM vendors"
        )
        receipts = self.fetch_one(
            "SELECT COUNT(*) AS total FROM vendor_creation_receipts"
        )
        events = self.fetch_one(
            """
            SELECT COUNT(*) AS total FROM task_events
            WHERE event_type = 'vendor_created'
            """
        )

        self.assertEqual(vendors["total"], 1)
        self.assertEqual(receipts["total"], 1)
        self.assertEqual(events["total"], 1)
        self.assert_task_status(task_id, "verifying")

    def test_verified_creation_completes_task(self):
        task_id = self.create_task()
        approval_id = self.create_approval(task_id)

        creation = execute_vendor_creation(task_id, approval_id)
        report = verify_vendor_creation(task_id, approval_id)

        self.assertTrue(report["passed"])
        self.assertEqual(report["vendor_id"], creation["vendor_id"])
        self.assertTrue(
            all(check["matches"] for check in report["checks"].values())
        )
        self.assert_task_status(task_id, "completed")

        event = self.fetch_one(
            """
            SELECT message FROM task_events
            WHERE task_id = ? AND event_type = 'verification_passed'
            ORDER BY id DESC LIMIT 1
            """,
            (task_id,),
        )
        self.assertIsNotNone(event)
        self.assertEqual(json.loads(event["message"]), report)

    def test_changed_vendor_field_fails_verification(self):
        task_id = self.create_task()
        approval_id = self.create_approval(task_id)

        creation = execute_vendor_creation(task_id, approval_id)

        # Alter only the isolated test database.
        self.execute_sql(
            "UPDATE vendors SET contact_email = ? WHERE id = ?",
            ("changed@example.com", creation["vendor_id"]),
        )

        report = verify_vendor_creation(task_id, approval_id)

        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["contact_email"]["matches"])
        self.assert_task_status(task_id, "failed")

        event = self.fetch_one(
            """
            SELECT message FROM task_events
            WHERE task_id = ? AND event_type = 'verification_failed'
            ORDER BY id DESC LIMIT 1
            """,
            (task_id,),
        )
        self.assertIsNotNone(event)
        self.assertEqual(json.loads(event["message"]), report)

    def test_missing_vendor_fails_verification(self):
        task_id = self.create_task()
        approval_id = self.create_approval(task_id)

        creation = execute_vendor_creation(task_id, approval_id)

        self.execute_sql(
            "DELETE FROM vendors WHERE id = ?",
            (creation["vendor_id"],),
        )

        report = verify_vendor_creation(task_id, approval_id)

        self.assertFalse(report["passed"])
        self.assertFalse(report["vendor_found"])
        self.assert_task_status(task_id, "failed")

    def test_second_approval_cannot_create_duplicate_vendor(self):
        first_task = self.create_task()
        first_approval = self.create_approval(first_task)
        execute_vendor_creation(first_task, first_approval)

        second_task = self.create_task()
        second_approval = self.create_approval(second_task)

        with self.assertRaisesRegex(
            ValueError,
            "matching vendor already exists",
        ):
            execute_vendor_creation(second_task, second_approval)

        vendors = self.fetch_one(
            "SELECT COUNT(*) AS total FROM vendors"
        )
        receipts = self.fetch_one(
            "SELECT COUNT(*) AS total FROM vendor_creation_receipts"
        )

        self.assertEqual(vendors["total"], 1)
        self.assertEqual(receipts["total"], 1)
        self.assert_task_status(second_task, "running")


if __name__ == "__main__":
    unittest.main(verbosity=2)