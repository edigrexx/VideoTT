import json

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.errors import NeedsReview
from app.schemas import Script
from app.services.llm import OpenAIProvider
from app.services.output import write_output
from app.services.subtitles import write_subtitles
from app.services.tts import Cue


def test_voice_and_language_must_agree_without_exposing_env():
    config = Settings(_env_file=None)
    assert config.content_language == "ru-RU"
    assert config.tts_voice == "ru-RU-SvetlanaNeural"
    assert "Russian" in config.language_instruction
    assert "ORIGINAL source language" in config.language_instruction
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, tts_voice="en-US-AriaNeural", llm_api_key="do-not-show-this-key")
    assert "do-not-show-this-key" not in str(error.value)
    english = Settings(_env_file=None, content_language="en-US", tts_voice="en-US-AriaNeural")
    assert "in English" in english.language_instruction


async def test_russian_script_metadata_caption_and_subtitles(sample, tmp_path):
    research, sources, original = sample
    payload = original.model_dump()
    # Keep the existing scene/fact structure, supply Russian audience-facing text.
    sentences = [
        "Пальцы умеют находить нужные клавиши. Небольшие выступы помогают почувствовать исходное положение рук на клавиатуре, не переводя взгляд вниз.",
        "Посмотрите на клавиши F и J. На многих клавиатурах именно там можно заметить маленькие полоски или выпуклые точки.",
        "Когда руки находятся в исходном положении, указательные пальцы касаются этих клавиш, а остальные располагаются рядом на том же ряду.",
        "Попробуйте ненадолго отвести руки от клавиатуры. Вернувшись к ней, осторожно найдите выступы подушечками пальцев и почувствуйте знакомое положение.",
        "Такая подсказка работает через прикосновение. Поэтому постоянно искать нужные клавиши глазами становится менее удобно, чем просто почувствовать ориентир пальцами.",
        "Выступы особенно понятны во время освоения печати. Они дают рукам заметную точку отсчёта, пока расположение клавиш ещё только запоминается.",
        "Форма подсказки может выглядеть по-разному. Где-то это короткая полоска, где-то небольшой выступ, который легко почувствовать кончиком указательного пальца.",
        "Эти детали не печатают за вас. Они лишь помогают вернуться к знакомому положению рук и продолжить работу с клавиатурой.",
        "Присмотритесь к своей клавиатуре и проверьте это прикосновением. Маленький выступ оказывается полезной подсказкой, которую легко было раньше не замечать.",
    ]
    for scene, text in zip(payload["scenes"], sentences, strict=True):
        scene["narration"] = text
    payload.update(
        title="Зачем клавишам выступы",
        hook="Пальцы умеют находить нужные клавиши.",
        payoff=sentences[-1].split(". ", 1)[1],
        narration=" ".join(sentences),
        caption="Найдите выступы на своей клавиатуре.",
        hashtags=["технологии", "клавиатура", "дизайн"],
    )
    script = Script.model_validate(payload)
    write_output(tmp_path, "ru-video", research.topic, script, sources, [], 75, language="ru-RU")
    assert json.loads((tmp_path / "metadata.json").read_text())["language"] == "ru-RU"
    assert "#клавиатура" in (tmp_path / "caption.txt").read_text()
    path = tmp_path / "subtitles.ass"
    write_subtitles([Cue(0, 1, "Найдите"), Cue(1, 2, "выступы")], 2, path)
    assert "выступы" in path.read_text()


async def test_english_answer_stops_russian_pipeline_before_tts(sample):
    research, _, script = sample
    provider = OpenAIProvider(Settings(_env_file=None, llm_api_key="test", llm_model="test"))

    async def structured(*args):
        return script

    provider.structured = structured
    try:
        with pytest.raises(NeedsReview) as error:
            await provider.generate_script(research)
        assert error.value.code == "LLM_LANGUAGE"
        provider.settings = Settings(_env_file=None, content_language="en-US", tts_voice="en-US-AriaNeural")
        assert await provider.generate_script(research) == script
    finally:
        await provider.close()
