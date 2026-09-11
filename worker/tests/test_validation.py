import pytest
from pydantic import ValidationError

from app.schemas import Script
from app.services.validation import validation_detail


@pytest.mark.parametrize(
    "violation,expected",
    [
        ("words", "Narration must contain 135–215 words"),
        ("order", "Scenes must be consecutive and ordered"),
        ("duration", "scenes.0.duration_hint: value above maximum"),
        ("hashtag", "hashtags.0: text does not match required pattern"),
        ("extra", "[field]: unexpected field"),
    ],
)
def test_actionable_validation_without_echoing_model_text(sample, violation, expected):
    payload = sample[2].model_dump()
    private = "secret-model-text"
    if violation == "words":
        for scene in payload["scenes"]:
            scene["narration"] = "Клавиатура"
        payload.update(
            hook="Клавиатура",
            payoff="Клавиатура",
            narration=" ".join(scene["narration"] for scene in payload["scenes"]),
        )
    elif violation == "order":
        payload["scenes"][0]["order"] = 2
    elif violation == "duration":
        payload["scenes"][0]["duration_hint"] = 25
    elif violation == "hashtag":
        payload["hashtags"][0] = "#" + private
    else:
        payload[private] = private
    with pytest.raises(ValidationError) as exc:
        Script.model_validate(payload)
    detail = validation_detail(Script, exc.value)
    assert detail.startswith("Script: ")
    assert expected in detail
    assert private not in detail


def test_invalid_json_does_not_echo_source():
    with pytest.raises(ValidationError) as exc:
        Script.model_validate_json("secret-model-text")
    assert validation_detail(Script, exc.value) == "Script: $: invalid JSON"
