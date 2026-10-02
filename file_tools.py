import re 
from pathlib import Path

DATA_ROOT = (Path(__file__).resolve().parent / "data").resolve()
MAX_FILE_BYTES = 100_000

import re
from pathlib import Path

DATA_ROOT = (Path(__file__).resolve().parent / "data").resolve()
MAX_FILE_BYTES = 100_000


def read_company_file(
    organization_id: str,
    relative_path: str,
) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", organization_id):
        raise ValueError("Invalid organization ID")

    company_root = (DATA_ROOT / organization_id).resolve()

    if not company_root.is_relative_to(DATA_ROOT):
        raise PermissionError("Company folder is outside the data folder")

    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise PermissionError("Use a relative file path")

    file_path = (company_root / requested_path).resolve()

    if not file_path.is_relative_to(company_root):
        raise PermissionError("File is outside this company's folder")

    if file_path.suffix.lower() not in {".md", ".txt", ".json", ".csv"}:
        raise ValueError("Unsupported file type")

    with file_path.open("rb") as file:
        raw_content = file.read(MAX_FILE_BYTES + 1)

    if len(raw_content) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 100,000-byte limit")

    return {
        "organization_id": organization_id,
        "path": file_path.relative_to(company_root).as_posix(),
        "content": raw_content.decode("utf-8"),
    }

def list_company_files(organization_id: str) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", organization_id):
        raise ValueError("Invalid organization ID")

    company_root = (DATA_ROOT / organization_id).resolve()

    if not company_root.is_relative_to(DATA_ROOT):
        raise PermissionError("Company folder is outside the data folder")

    if not company_root.is_dir():
        raise FileNotFoundError("Company folder does not exist")

    files = []

    for path in company_root.rglob("*"):
        resolved_path = path.resolve()

        if not resolved_path.is_relative_to(company_root):
            continue

        if not resolved_path.is_file():
            continue

        if resolved_path.suffix.lower() not in {
            ".md", ".txt", ".json", ".csv"
        }:
            continue

        files.append(path.relative_to(company_root).as_posix())

    return {
        "organization_id": organization_id,
        "files": sorted(files),
    }