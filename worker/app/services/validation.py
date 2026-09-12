"""Validation diagnostics that never include model-supplied text or field names."""

import json

from pydantic import ValidationError

from app.schemas import ScriptDraft, narration_word_count


def script_length_guidance(content, language, *, draft_format=False):
    """Give the writer measured counts, not another request to count its own words."""
    try:
        draft = json.loads(content)
    except (ValueError, TypeError):
        return ""
    if not isinstance(draft, dict):
        return ""
    hook_guidance = ""
    if isinstance(draft.get("hook"), str):
        hook_guidance = (
            f" Measured hook: {len(draft['hook'].split())} words; maximum 10. Aim for 6 words in the hook. "
            "The hook is one short sentence, not the entire first scene. Move supporting detail into "
            "the first scene body, preserving the supported meaning."
        )
    if draft_format:
        try:
            draft = ScriptDraft.model_validate(draft).assembled_data()
        except ValidationError:
            return hook_guidance
    if not isinstance(draft.get("narration"), str):
        return hook_guidance
    scenes = draft.get("scenes")
    if not isinstance(scenes, list) or not 8 <= len(scenes) <= 16:
        return ""
    if any(not isinstance(scene, dict) or not isinstance(scene.get("narration"), str) for scene in scenes):
        return ""
    target = 153 if language == "ru-RU" else 171
    total = narration_word_count(draft["narration"])
    counts = [narration_word_count(scene["narration"]) for scene in scenes]
    base, remainder = divmod(target, len(scenes))
    budgets = [base + (index < remainder) for index in range(len(scenes))]
    assembly_guidance = "Then join the scenes into narration."
    if draft_format:
        body_budgets = budgets.copy()
        body_budgets[0] = max(1, body_budgets[0] - 6)
        body_budgets[-1] = max(1, body_budgets[-1] - 10)
        assembly_guidance = (
            f"For the returned scene BODY fields only, aim for {body_budgets} words; these exclude "
            "the separate hook (about 6 words) and payoff (about 10 words). The application adds those "
            "once and joins everything. Do not repeat hook/payoff in bodies or return full narration or orders."
        )
    change = f"add about {target - total}" if total < target else f"remove about {total - target}"
    return (
        f" Measured narration: {total} words. Scene word counts in order: {counts}; sum {sum(counts)}. "
        f"Target {target} total spoken words; {change} words to reach this target. "
        f"Rewrite scene narrations toward these per-scene word budgets: {budgets}. "
        "Hook and payoff are INCLUDED in these budgets, never counted twice. Count only spoken narration, "
        "not title, caption, hashtags, visual queries or the duplicate full narration field. "
        "For short text, explain the supplied facts in clearer complete sentences or use simple viewer "
        "instructions; do not pad with repetition or invent details. For long text, remove repetition and "
        "shorten phrasing without changing the supported claims. " + assembly_guidance + hook_guidance
    )


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
    for item in error.errors(include_input=False, include_context=True, include_url=False)[:6]:
        path = (
            ".".join(
                str(part) if isinstance(part, int) or part in fields else "[field]" for part in item["loc"]
            )
            or "$"
        )
        message = messages.get(item["type"], "invalid value or type")
        if item["type"] == "narration_word_count":
            actual = (item.get("ctx") or {}).get("actual")
            if type(actual) is int:
                message = f"Narration must contain 135–215 words; got {actual}"
        if item["type"] == "hook_word_count":
            actual = (item.get("ctx") or {}).get("actual")
            if type(actual) is int:
                message = f"Opening hook must contain at most 10 words; got {actual}"
        if item["type"] == "value_error":
            known = item["msg"].removeprefix("Value error, ")
            if known in consistency_messages:
                message = known
        issues.append(f"{path}: {message}")
    return f"{schema.__name__}: " + "; ".join(issues)
