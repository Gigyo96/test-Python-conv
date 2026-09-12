"""Classifying how an utterance trails off.

A pause means very different things after "I went to Rome" and after "I went to".
Reading the tail of the partial transcript is a cheap way to tell the two apart,
and it costs nothing on the critical path -- which a turn-detection model would
not.

The word lists are deliberately **conservative**. English is full of tokens that
look incomplete but routinely end a sentence: "Yes, I do", "I think so", "I have
never been there... well, once". Every false positive adds half a second of dead
air to exactly the short, snappy exchanges Part 1 is made of, so a token earns
its place here only if it essentially cannot end an utterance.

The lists are meant to be extended from replay data, not to be complete on the
first try.
"""

import re
from enum import StrEnum

_HESITATIONS: frozenset[str] = frozenset(
    {"um", "uh", "erm", "ehm", "hmm", "hm", "mm", "mmm", "er", "ah", "eh"}
)
"""Vocal fillers. None of these is ever a real word ending a real sentence."""

_OPENING_MARKERS: frozenset[str] = frozenset({"well", "like", "so", "right", "okay", "actually"})
"""Discourse markers, which only count as hesitation while nothing else has been said.

"Well" is someone gathering their thoughts; "it went well" is a finished
sentence, and "I think so" is one of the most common answers in Part 1. The rule
that separates them is that a marker is hesitation only when the transcript so
far contains nothing but filler -- see :func:`_is_all_filler`.
"""

_HESITATION_PHRASES: frozenset[tuple[str, ...]] = frozenset(
    {
        ("i", "mean"),
        ("you", "know"),
        ("sort", "of"),
        ("kind", "of"),
        ("how", "can", "i", "say"),
        ("what", "i", "mean", "is"),
    }
)
"""Multi-token fillers, matched as a suffix. Unambiguous regardless of position."""

_DANGLING: frozenset[str] = frozenset(
    {
        # Subordinators and coordinators. "so" is excluded: "I think so" is a
        # complete answer, and a very common one.
        "and",
        "but",
        "or",
        "because",
        "although",
        "though",
        "whereas",
        "unless",
        "while",
        "since",
        "whether",
        "than",
        "whom",
        "whose",
        # Prepositions that cannot stand as particles. "in", "on", "at", "up",
        # "out" are excluded: they end plenty of sentences ("come in", "grew up").
        "of",
        "to",
        "with",
        "from",
        "into",
        "onto",
        "upon",
        "toward",
        "towards",
        "between",
        "among",
        "during",
        "without",
        "within",
        "against",
        "despite",
        # Determiners and possessive adjectives. The possessive *pronouns*
        # (mine, yours, hers, theirs) are different words and are not listed.
        "the",
        "a",
        "an",
        "my",
        "your",
        "his",
        "her",
        "its",
        "our",
        "their",
    }
)
"""Tokens that cannot end a well-formed utterance.

Notably absent: auxiliaries and modals. "Yes, I do", "Yes, I have", "Yes, I can"
are the most ordinary answers in Part 1, and treating them as incomplete would
make the examiner hesitate after every one of them.
"""

_SENTENCE_ENDINGS = ".?!"
"""Punctuation a recogniser emits when it is confident a sentence closed."""

_TOKEN_PATTERN = re.compile(r"[a-z']+")


class Tail(StrEnum):
    """How the transcript ends, as far as the policy is concerned."""

    HESITATION = "hesitation"
    """Trails off into a filler. The candidate is thinking, not finishing."""

    DANGLING = "dangling"
    """Ends mid-construction. Grammatically something must follow."""

    COMPLETE = "complete"
    """Could plausibly be the end of a sentence.

    Also the answer for an empty transcript: no information is treated as no
    adjustment, never as evidence that the turn is still running.
    """


def classify_tail(transcript: str) -> Tail:
    """Classify how ``transcript`` ends.

    Args:
        transcript: partial transcript of the turn so far. May be empty.

    Returns:
        The tail classification driving the endpointing adjustments.
    """
    stripped = transcript.strip()
    if not stripped:
        return Tail.COMPLETE

    # A recogniser confident enough to emit terminal punctuation is a stronger
    # signal than anything the word lists can infer, so it wins outright.
    if stripped[-1] in _SENTENCE_ENDINGS:
        return Tail.COMPLETE

    tokens = _TOKEN_PATTERN.findall(stripped.lower())
    if not tokens:
        return Tail.COMPLETE

    if _ends_with_hesitation_phrase(tokens):
        return Tail.HESITATION

    last = tokens[-1]
    if last in _HESITATIONS:
        return Tail.HESITATION
    if last in _OPENING_MARKERS and _is_all_filler(tokens):
        return Tail.HESITATION
    if last in _DANGLING:
        return Tail.DANGLING
    return Tail.COMPLETE


def _is_all_filler(tokens: list[str]) -> bool:
    """Whether the candidate has produced nothing but filler so far."""
    return all(token in _HESITATIONS or token in _OPENING_MARKERS for token in tokens)


def _ends_with_hesitation_phrase(tokens: list[str]) -> bool:
    """Whether ``tokens`` ends with any known multi-token filler."""
    return any(
        len(tokens) >= len(phrase) and tuple(tokens[-len(phrase) :]) == phrase
        for phrase in _HESITATION_PHRASES
    )
