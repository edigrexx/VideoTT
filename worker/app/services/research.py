import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.errors import NeedsReview
from app.services.network import bounded_fetch, retry_call


def normalise(text):
    return " ".join(re.findall(r"[\w]+", text.casefold()))


async def retrieve_sources(candidates, settings):
    sources = []
    seen = set()
    for candidate in candidates[:8]:
        url = candidate["url"]
        if url in seen:
            continue
        seen.add(url)
        try:

            async def fetch():
                return await bounded_fetch(
                    url,
                    limit=1_500_000,
                    timeout=settings.http_timeout_sec,
                    types=("text/html", "text/plain", "application/xhtml+xml"),
                )

            async with asyncio.timeout(settings.http_timeout_sec * 4):
                raw = await retry_call(fetch)
            soup = BeautifulSoup(raw, "html.parser")
            for node in soup(["script", "style", "nav", "header", "footer", "noscript"]):
                node.decompose()
            excerpt = " ".join(soup.get_text(" ", strip=True).split())[:18000]
            if len(excerpt) < 200:
                continue
            sources.append(
                {
                    "title": candidate.get("title") or urlsplit(url).hostname,
                    "url": url,
                    "publisher": urlsplit(url).hostname,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "excerpt": excerpt,
                }
            )
        except Exception:
            # Blocked/paywalled/unsafe/unreachable sources are never treated as verified.
            continue
    if len({s["publisher"] for s in sources}) < 2:
        raise NeedsReview(
            "INSUFFICIENT_SOURCES", "Could not retrieve sources from at least two public domains"
        )
    return sources


def validate_fact_evidence(research, sources):
    lookup = {s["url"]: normalise(s["excerpt"]) for s in sources}
    ids = [fact.id for fact in research.facts]
    if len(ids) != len(set(ids)):
        raise NeedsReview("FACT_IDS", "Research contains duplicate fact identifiers")
    for index, fact in enumerate(research.facts):
        if len(fact.source_urls) != len(fact.evidence_quotes):
            raise NeedsReview(
                "FACT_EVIDENCE",
                f"facts[{index}]: {len(fact.source_urls)} source URLs but {len(fact.evidence_quotes)} quotes; "
                "every source needs its own evidence quote",
            )
        for pair, (url, quote) in enumerate(zip(fact.source_urls, fact.evidence_quotes, strict=True)):
            location = f"facts[{index}].evidence[{pair}]"
            if url not in lookup:
                reason = "source URL is missing from retrieved sources"
            elif len(normalise(quote)) < 20:
                reason = "quote is too short (at least 20 normalized characters required)"
            elif normalise(quote) not in lookup[url]:
                reason = (
                    "quote is missing from the retrieved source text; copy one continuous original passage"
                )
            else:
                continue
            raise NeedsReview("FACT_EVIDENCE", f"{location}: {reason}")


def validate_script_evidence(script, research, evaluation, threshold):
    known = {fact.id for fact in research.facts}
    if any(not set(scene.fact_ids) <= known for scene in script.scenes):
        raise NeedsReview("UNSUPPORTED_FACT", "Script references a fact absent from the research")
    if (
        not evaluation.supported
        or evaluation.confidence < threshold
        or evaluation.contradictions
        or evaluation.unsupported_claims
    ):
        raise NeedsReview(
            "FACT_CHECK_FAILED",
            "Independent script validation found insufficient evidence; inspect evaluation",
        )
