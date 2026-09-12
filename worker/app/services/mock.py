"""Deliberately synthetic offline fixtures; never claimed to be researched production videos."""

from datetime import datetime, timezone

from app.errors import PipelineError
from app.schemas import Evaluation, ResearchResult, Script

SAMPLE_TOPIC = "Why do the F and J keys on keyboards have raised bumps?"
NARRATIONS = [
    "Your fingers have a home address. Look closely at a typical keyboard and find the letters F and J.",
    "On many keyboards, those two keys have small raised marks. You can feel these marks without looking down at the keys.",
    "The marks help you find a starting position by touch. Place your left index finger on F and your right on J.",
    "This position is part of the home row used in touch typing. The marks give your index fingers a physical reference.",
    "Try lifting your hands away for a moment. Then bring them back and feel for the raised marks with your fingertips.",
    "You can use that small tactile clue to locate the starting position again. The useful information is something you feel.",
    "Now compare that with searching visually for a printed letter. The raised mark gives your finger another way to find its place.",
    "The interesting detail is how little material this takes. A tiny surface feature can serve as a reference for your hands.",
    "Next time you sit at a keyboard, try finding those marks before looking down. A tiny bump points your fingers home.",
]


class MockLLMProvider:
    async def research_topic(self, topic):
        if topic != SAMPLE_TOPIC:
            raise PipelineError(
                "MOCK_TOPIC_ONLY", "Offline fixtures support only the sample F and J keyboard topic"
            )
        excerpt = "On many keyboards, the F and J keys have raised marks. These tactile marks help index fingers locate the home row starting position in touch typing."
        url = "fixture://keyboard-test"
        sources = [
            {
                "title": "Synthetic test fixture; not independently researched",
                "url": url,
                "publisher": "local-test-fixture",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "excerpt": excerpt,
            }
        ]
        research = ResearchResult(
            topic=topic,
            summary=excerpt,
            facts=[
                {
                    "id": "f1",
                    "text": "F and J often have raised marks",
                    "source_urls": [url],
                    "evidence_quotes": ["On many keyboards, the F and J keys have raised marks."],
                },
                {
                    "id": "f2",
                    "text": "The marks locate the starting position",
                    "source_urls": [url],
                    "evidence_quotes": [
                        "These tactile marks help index fingers locate the home row starting position in touch typing."
                    ],
                },
            ],
        )
        return research, sources

    async def generate_script(self, research):
        return Script(
            title="Your keyboard's tiny guide",
            hook="Your fingers have a home address.",
            payoff="A tiny bump points your fingers home.",
            narration=" ".join(NARRATIONS),
            estimated_duration=76,
            scenes=[
                {
                    "order": i + 1,
                    "narration": text,
                    "visual_query": "close up of fingers resting on keyboard home row",
                    "visual_query_fallback": "typing on computer keyboard",
                    "duration_hint": 8,
                    "fact_ids": ["f1", "f2"],
                }
                for i, text in enumerate(NARRATIONS)
            ],
            caption="A tiny keyboard detail you can feel. TEST FIXTURE — review before any use.",
            hashtags=["technology", "keyboard", "design"],
        )

    async def evaluate_script(self, script, research, sources):
        return Evaluation(
            supported=True,
            confidence=1,
            contradictions=[],
            unsupported_claims=[],
            explanation="Offline fixture validation only. No external fact checking was performed.",
        )
