"""Validation diagnostics that never include model-supplied text or field names."""


def validation_detail(schema, error):
    fields = set()

    def collect(node):
        if isinstance(node, dict):
            fields.update(node.get("properties", {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(schema.model_json_schema())
    consistency_messages = {
        "Narration must equal concatenated scene narration",
        "Scenes must be consecutive and ordered",
        "Narration must start with hook and end with payoff",
        "Keep the opening hook to 10 words or fewer",
        "Narration must contain 135–215 words",
    }
    messages = {
        "missing": "required field missing",
        "extra_forbidden": "unexpected field",
        "json_invalid": "invalid JSON",
        "string_type": "expected text",
        "string_too_short": "text too short",
        "string_too_long": "text too long",
        "string_pattern_mismatch": "text does not match required pattern",
        "too_short": "too few items",
        "too_long": "too many items",
        "greater_than": "value must exceed lower bound",
        "greater_than_equal": "value below minimum",
        "less_than": "value must be below upper bound",
        "less_than_equal": "value above maximum",
    }
    issues = []
    for item in error.errors(include_input=False, include_context=False, include_url=False)[:6]:
        path = (
            ".".join(
                str(part) if isinstance(part, int) or part in fields else "[field]" for part in item["loc"]
            )
            or "$"
        )
        message = messages.get(item["type"], "invalid value or type")
        if item["type"] == "value_error":
            known = item["msg"].removeprefix("Value error, ")
            if known in consistency_messages:
                message = known
        issues.append(f"{path}: {message}")
    return f"{schema.__name__}: " + "; ".join(issues)
