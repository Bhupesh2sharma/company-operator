from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


PORTAL_URL = "http://127.0.0.1:8000/portal"
VENDOR_ID = "174a4000-22ea-4520-8bd3-d5d278191bf6"

EXPECTED_FIELDS = {
    "id": VENDOR_ID,
    "organization_id": "demo-company",
    "legal_name": "Northstar Demo Services LLP",
    "contact_email": "northstar@example.com",
    "registered_address": "25 Example Avenue, Demo City",
    "service_category": "Office maintenance",
}


def main():
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence_dir = (
        Path(__file__).resolve().parent / "evidence" / run_id
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            slow_mo=150,
        )
        page = browser.new_page(
            viewport={"width": 1280, "height": 900}
        )
        page.set_default_timeout(10_000)
        expect.set_options(timeout=10_000)

        try:
            page.goto(PORTAL_URL)

            page.get_by_label("Organization ID").fill("demo-company")
            page.get_by_label("Vendor ID", exact=True).fill(VENDOR_ID)
            page.get_by_role("button", name="Find vendor").click()

            expect(page.locator("#status")).to_have_text(
                "Vendor record loaded."
            )
            expect(page.locator("#vendor-result")).to_be_visible()

            for field, expected_value in EXPECTED_FIELDS.items():
                expect(
                    page.locator(f'[data-field="{field}"]')
                ).to_have_text(expected_value)

            page.screenshot(
                path=str(evidence_dir / "vendor-found.png"),
                full_page=True,
            )
            print("PASS: Saved vendor fields match expected values.")

            page.get_by_label("Organization ID").fill("other-company")
            page.get_by_role("button", name="Find vendor").click()

            expect(page.locator("#status")).to_have_text(
                "Vendor not found for this organization."
            )
            expect(page.locator("#vendor-result")).to_be_hidden()
            expect(page.locator("#vendor-fields")).to_be_empty()

            page.screenshot(
                path=str(evidence_dir / "vendor-not-found.png"),
                full_page=True,
            )
            print("PASS: Other organization returns no vendor details.")

            page.get_by_label("Organization ID").fill("demo-company")
            page.get_by_role("button", name="Find vendor").click()

            expect(page.locator("#status")).to_have_text(
                "Vendor record loaded."
            )
            expect(page.locator("#vendor-result")).to_be_visible()

            for field, expected_value in EXPECTED_FIELDS.items():
                expect(
                    page.locator(f'[data-field="{field}"]')
                ).to_have_text(expected_value)

            print("PASS: Switching back restores the correct record.")

        except Exception:
            try:
                page.screenshot(
                    path=str(evidence_dir / "failure.png"),
                    full_page=True,
                )
            except Exception:
                pass
            raise

        finally:
            browser.close()
            print("Evidence folder:", evidence_dir)


if __name__ == "__main__":
    main()