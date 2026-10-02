from database import get_connection


def normalize_legal_name(legal_name: str) -> str:
    normalized = " ".join(legal_name.split()).casefold()

    if not normalized:
        raise ValueError("Legal name cannot be empty")

    return normalized


def search_vendors(
    organization_id: str,
    legal_name: str,
) -> dict:
    name_key = normalize_legal_name(legal_name)
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT id, legal_name, contact_email,
                   registered_address, service_category
            FROM vendors
            WHERE organization_id = ?
              AND legal_name_key = ?
            ORDER BY id
            """,
            (organization_id, name_key),
        ).fetchall()
    finally:
        connection.close()

    return {
        "organization_id": organization_id,
        "query": legal_name,
        "match_type": "normalized_exact",
        "matches": [dict(row) for row in rows],
    }