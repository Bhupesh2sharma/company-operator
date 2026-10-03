import re
from pathlib import Path
from uuid import UUID, uuid4

from playwright.sync_api import expect, sync_playwright


PORTAL_URL = "http://127.0.0.1:8000/portal"
EVIDENCE_ROOT = Path(__file__).resolve().parent / "evidence"

DISPLAYED_FIELDS = (
    "id",
    "organization_id",
    "legal_name",
    "contact_email",
    "registered_address",
    "service_category",
    "created_at",
)


def inspect_vendor_in_browser(
    organization_id: str,
    vendor_id: str,
) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", organization_id):
        raise ValueError("Invalid organization ID")

    vendor_id = str(UUID(vendor_id))

    evidence_dir = EVIDENCE_ROOT / str(uuid4())
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = evidence_dir / "vendor-lookup.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        try:
            page = browser.new_page(
                viewport={"width": 1280, "height": 900}
            )
            page.set_default_timeout(10_000)

            page.goto(PORTAL_URL)

            page.get_by_label("Organization ID").fill(organization_id)
            page.get_by_label("Vendor ID", exact=True).fill(vendor_id)
            page.get_by_role("button", name="Find vendor").click()

            status = page.locator("#status")

            expect(status).to_have_text(
                re.compile(
                    r"^(Vendor record loaded\.|"
                    r"Vendor not found for this organization\.)$"
                ),
                timeout=10_000,
            )

            found = status.inner_text() == "Vendor record loaded."
            observed = None

            if found:
                expect(
                    page.locator("#vendor-result")
                ).to_be_visible()

                observed = {
                    field: page.locator(
                        f'[data-field="{field}"]'
                    ).inner_text()
                    for field in DISPLAYED_FIELDS
                }

                if (
                    observed["id"] != vendor_id
                    or observed["organization_id"] != organization_id
                ):
                    raise RuntimeError(
                        "Portal displayed a different vendor or organization"
                    )
            else:
                expect(
                    page.locator("#vendor-result")
                ).to_be_hidden()

                expect(
                    page.locator("#vendor-fields")
                ).to_be_empty()

            page.screenshot(
                path=str(screenshot_path),
                full_page=True,
            )

            return {
                "organization_id": organization_id,
                "vendor_id": vendor_id,
                "found": found,
                "observed": observed,
                "screenshot_path": str(screenshot_path),
                "source": PORTAL_URL,
            }

        finally:
            browser.close()