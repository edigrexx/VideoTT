import pytest

from app.services.relevance import keywords, relevance


@pytest.mark.parametrize(
    "text,expected",
    [
        ("floppy disk", ["floppy", "disk"]),
        ("Floppy Disks", ["floppy", "disk"]),
        ("close up of a person holding a VHS tape", ["holding", "vhs", "tape"]),
        ("a-person-ejecting-cd-from-the-disk-tray", ["ejecting", "disk", "tray"]),
        ("", []),
        ("the a of on", []),
    ],
)
def test_keywords_drop_filler_and_fold_plurals(text, expected):
    assert keywords(text) == expected


def test_keywords_are_unique_and_ordered():
    assert keywords("disk disk drive disks") == ["disk", "drive"]


@pytest.mark.parametrize(
    "description,expected",
    [
        ("floppy disk 80s computer retro diskette", 1.0),
        ("inserting floppy disk into vintage commodore 1541", 1.0),
        ("a person ejecting cd from the disk tray", 0.5),
        ("close up of a beagle s nose outdoors", 0.0),
        ("", 0.0),
    ],
)
def test_relevance_scores_real_catalogue_descriptions(description, expected):
    # Descriptions copied verbatim from a live Pexels page for the query "floppy disk".
    assert relevance("floppy disk", description) == expected


def test_relevance_of_a_query_without_content_words_is_zero():
    assert relevance("the a of", "floppy disk") == 0.0


def test_long_descriptive_query_cannot_match_its_own_best_result():
    """Why the prompt asks for keywords: a sentence scores below the weak tier."""
    sentence = "hands inserting floppy disk into old computer"
    assert relevance(sentence, "inserting floppy disk into vintage commodore 1541") < 0.6
    assert relevance("floppy disk", "inserting floppy disk into vintage commodore 1541") == 1.0


def test_letters_outside_ascii_are_not_dropped():
    """Russian titles and hooks are compared with the same scorer."""
    assert keywords("Виниловые пластинки хранят звук") == ["виниловые", "пластинки", "хранят", "звук"]
    assert keywords("café lights") == ["café", "light"]


def test_a_reworded_russian_title_still_scores_as_the_title():
    # The hook a live run actually produced, against that run's title.
    hook = "Как виниловые пластинки хранят наш звук?"
    assert relevance(hook, "Как виниловые пластинки хранят звук") >= 0.6
    assert relevance("В канавке нет ни одного бита", "Как виниловые пластинки хранят звук") < 0.6
