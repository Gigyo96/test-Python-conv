"""Encoding and parsing of the browser protocol."""

import pytest

from ielts_examiner.domain.phase import Phase
from ielts_examiner.server.protocol import (
    ClientError,
    Hello,
    PhaseChanged,
    PlaybackFinished,
    Ready,
    SessionEnd,
    StopPlayback,
    UtteranceBegin,
    UtteranceEnd,
    encode,
    parse,
)


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (Ready(), {"type": "ready"}),
        (PhaseChanged(phase=Phase.PART2_LONG_TURN), {"type": "phase", "phase": "part2_long_turn"}),
        (
            UtteranceBegin(utterance_id=1, text="Good morning."),
            {"type": "utterance_begin", "utterance_id": 1, "text": "Good morning."},
        ),
        (UtteranceEnd(utterance_id=1), {"type": "utterance_end", "utterance_id": 1}),
        (StopPlayback(), {"type": "stop_playback"}),
        (SessionEnd(reason="completed"), {"type": "session_end", "reason": "completed"}),
    ],
)
def test_server_events_encode_to_flat_json(event: object, expected: dict) -> None:
    import json

    assert json.loads(encode(event)) == expected  # type: ignore[arg-type]


def test_phases_are_encoded_as_their_value_not_their_repr() -> None:
    """The browser matches on the string, so the enum must not leak."""
    assert '"phase": "part1"' in encode(PhaseChanged(phase=Phase.PART1))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"type": "hello", "sample_rate": 16000}', Hello(sample_rate=16000)),
        ('{"type": "playback_finished", "utterance_id": 4}', PlaybackFinished(utterance_id=4)),
        ('{"type": "client_error", "message": "no mic"}', ClientError(message="no mic")),
    ],
)
def test_client_messages_parse_to_types(text: str, expected: object) -> None:
    assert parse(text) == expected


@pytest.mark.parametrize(
    "text",
    ["not json", '{"type": "telepathy"}', '{"no_type": 1}', '{"type": "hello", "wrong": 1}'],
)
def test_unrecognised_client_messages_are_rejected(text: str) -> None:
    """The browser is our own code: anything unexpected is a bug, not input."""
    with pytest.raises(ValueError):
        parse(text)
