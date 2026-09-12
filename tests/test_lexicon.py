"""How the tail of a partial transcript is read."""

import pytest

from ielts_examiner.turntaking.lexicon import Tail, classify_tail


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        ("", Tail.COMPLETE),
        ("   ", Tail.COMPLETE),
        ("I live in Rome", Tail.COMPLETE),
        ("I live in Rome.", Tail.COMPLETE),
        ("Do you think so?", Tail.COMPLETE),
        ("I think um", Tail.HESITATION),
        ("it was, you know", Tail.HESITATION),
        ("it was sort of", Tail.HESITATION),
        ("I would say, I mean", Tail.HESITATION),
        ("I went to", Tail.DANGLING),
        ("because", Tail.DANGLING),
        ("my favourite is the", Tail.DANGLING),
    ],
)
def test_classify_tail(transcript: str, expected: Tail) -> None:
    assert classify_tail(transcript) is expected


def test_terminal_punctuation_outranks_the_word_lists() -> None:
    """A recogniser confident enough to close the sentence is believed."""
    assert classify_tail("I went to") is Tail.DANGLING
    assert classify_tail("I went to.") is Tail.COMPLETE


def test_classification_ignores_case_and_punctuation() -> None:
    assert classify_tail("Well, I think, um,") is Tail.HESITATION


@pytest.mark.parametrize(
    "answer",
    ["yes I do", "no I have not", "yes I can", "I think so", "yes I did", "I agree with that"],
)
def test_ordinary_short_answers_are_complete(answer: str) -> None:
    """The most common Part 1 answers must not be read as unfinished.

    Auxiliaries and modals end English short answers constantly. Treating them as
    dangling would add half a second of dead air to every brisk exchange -- the
    exact opposite of what the extension is for.
    """
    assert classify_tail(answer) is Tail.COMPLETE


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        ("well", Tail.HESITATION),
        ("so", Tail.HESITATION),
        ("I think it went well", Tail.COMPLETE),
        ("the interview went so", Tail.COMPLETE),
    ],
)
def test_discourse_markers_are_hesitation_only_when_they_open_the_turn(
    transcript: str, expected: Tail
) -> None:
    assert classify_tail(transcript) is expected
