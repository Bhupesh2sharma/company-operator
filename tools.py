from pydantic import BaseModel, ConfigDict, Field, ValidationError
from vendor_tools import search_vendors
from approvals import VendorProposal
from file_tools import read_company_file, list_company_files
class ReadFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    relative_path: str = Field(min_length=1, max_length=500)

class ListFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
class SearchVendorsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    legal_name: str = Field(min_length=1, max_length=200)
TOOL_REGISTRY = {
    "read_company_file": {
        "description": "Read a text document inside the current company's folder.",
        "arguments_model": ReadFileArguments,
        "handler": read_company_file,
    },
    "list_company_files": {
        "description": "List available text documents for the current company.",
        "arguments_model": ListFilesArguments,
        "handler": list_company_files,
    },
        "search_vendors": {
        "description": (
            "Search the current company's vendor database by legal name. "
            "Matches ignore capitalization and repeated whitespace. "
            "An empty result means no normalized exact match; "
            "it does not rule out spelling variations."
        ),
        "arguments_model": SearchVendorsArguments,
        "handler": search_vendors,
    },
}


def execute_tool(
    tool_name: str,
    arguments: dict,
    *,
    organization_id: str,
) -> dict:
    tool = TOOL_REGISTRY.get(tool_name)

    if tool is None:
        return {
            "ok": False,
            "tool": tool_name,
            "error": {
                "type": "unknown_tool",
                "message": "This tool is not available",
            },
        }

    try:
        validated = tool["arguments_model"].model_validate(arguments)

        result = tool["handler"](
            organization_id=organization_id,
            **validated.model_dump(),
        )

        return {
            "ok": True,
            "tool": tool_name,
            "data": result,
        }

    except ValidationError:
        error_type = "invalid_arguments"
        message = "Arguments do not match the tool's required schema."

    except PermissionError:
        error_type = "permission_denied"
        message = "Access to the requested file is denied."

    except FileNotFoundError:
        error_type = "file_not_found"
        message = "The requested file does not exist."

    except (ValueError, IsADirectoryError):
        error_type = "invalid_file"
        message = "The file path, type, size, or encoding is invalid."

    return {
        "ok": False,
        "tool": tool_name,
        "error": {
            "type": error_type,
            "message": message,
        },
    }

def get_tool_definitions() -> list[dict]:
    definitions = []

    for name, tool in TOOL_REGISTRY.items():
        definitions.append({
            "name": name,
            "description": tool["description"],
            "parameters": tool["arguments_model"].model_json_schema(),
        })

    definitions.append({
        "name": "request_vendor_approval",
        "description": (
            "Request human approval to create a vendor using the "
            "exact proposed details. Read the company policy and "
            "vendor documents and check existing vendors first. "
            "Do not invent missing information. "
            "This pauses the task; it does not approve or create a vendor."
        ),
        "parameters": VendorProposal.model_json_schema(),
    })

    return definitions
    definitions = []

    for name, tool in TOOL_REGISTRY.items():
        definitions.append({
            "name": name,
            "description": tool["description"],
            "parameters": tool["arguments_model"].model_json_schema(),
        })

    return definitions   