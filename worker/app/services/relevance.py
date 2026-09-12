"""Rank stock candidates by how well their own description matches the search query.

Stock search never reports "no match": Pexels answers a nonsense query with a full
page of loosely keyword-matched clips. Measured on the live API, `floppy disk`
returns 79 videos of which 71 share no content word with the query. Picking the
first downloadable result therefore picks noise. Every provider ships a short
human description (a Pexels URL slug, Pixabay tags), which is enough signal to
separate a real match from a clip that merely contains one common word.
"""

import re

# Words that carry no topical meaning in a stock description or a search query.
STOPWORDS = frozenset(
    """a an the of on in at to and or with for from by as is are was were be being been
    this that these those it its his her their our your my
    close up macro shot clip video footage scene view angle background
    person people man woman men women guy girl boy kid child adult someone""".split()
)


def keywords(text):
    """Content words, lowercased and crudely singularized so plurals still match.

    Letters are matched in any alphabet: stock queries and descriptions are
    English, but the same scoring compares Russian hooks against Russian titles.
    """
    found = []
    for word in re.findall(r"[^\W\d_]+", (text or "").lower()):
        if len(word) < 3 or word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        if word not in found:
            found.append(word)
    return found


def relevance(query, description):
    """Share of the query's content words that the description actually contains."""
    wanted = keywords(query)
    if not wanted:
        return 0.0
    available = set(keywords(description))
    return sum(word in available for word in wanted) / len(wanted)
