import json

from approvals import VendorProposal, request_vendor_approval


if __name__ == "__main__":
    proposal = VendorProposal(
        legal_name="Sample Vendor LLP",
        contact_email="operations@example.com",
        registered_address="10 Demo Street, Example City",
        service_category="IT services",
    )

    result = request_vendor_approval(
        task_id="27252d59-be87-4560-a05e-8316b8700c35",
        proposal=proposal,
    )

    print(json.dumps(result, indent=2))