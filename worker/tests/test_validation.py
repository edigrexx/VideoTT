import pytest
from pydantic import ValidationError

from app.schemas import Script, narration_word_count
from app.services.validation import script_length_guidance, validation_detail


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
    if violation == "words":
        assert "got 9" in detail


def test_invalid_json_does_not_echo_source():
    with pytest.raises(ValidationError) as exc:
        Script.model_validate_json("secret-model-text")
    assert validation_detail(Script, exc.value) == "Script: $: invalid JSON"


def test_word_count_handles_russian_and_hyphenated_words():
    assert narration_word_count("F и J — тактильные метки. Кто-то их замечает!") == 8


@pytest.mark.parametrize("length,accepted", [(134, False), (135, True), (215, True), (216, False)])
def test_word_count_boundaries_remain_enforced(sample, length, accepted):
    payload = sample[2].model_dump()
    base, rest = divmod(length, len(payload["scenes"]))
    for index, scene in enumerate(payload["scenes"]):
        scene["narration"] = " ".join(["слово"] * (base + (index < rest)))
    payload.update(
        narration=" ".join(scene["narration"] for scene in payload["scenes"]), hook="слово", payoff="слово"
    )
    if accepted:
        assert narration_word_count(Script.model_validate(payload).narration) == length
    else:
        with pytest.raises(ValidationError) as exc:
            Script.model_validate(payload)
        assert exc.value.errors()[0]["type"] == "narration_word_count"
        assert f"got {length}" in validation_detail(Script, exc.value)


@pytest.mark.parametrize("content", ["broken", "[]", "{}", '{"narration": "private", "scenes": [1]}'])
def test_length_guidance_ignores_malformed_drafts(content):
    assert script_length_guidance(content, "ru-RU") == ""
