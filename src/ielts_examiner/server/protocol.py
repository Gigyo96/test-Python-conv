"""Messages exchanged with the browser.

One WebSocket carries both directions. Binary frames are audio -- microphone
going up, examiner going down -- and text frames are JSON control messages. The
split means audio never pays for base64 and control never has to be framed by
hand.

Every message is a frozen dataclass. Parsing happens once, at the edge, so the
session runner works with types rather than dictionaries.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any

from ielts_examiner.domain.phase import Phase


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """Microphone audio from the browser: 16 kHz mono PCM16."""

    pcm: bytes


@dataclass(frozen=True, slots=True)
class Hello:
    """First message of a session, carrying what the browser negotiated."""

    sample_rate: int


@dataclass(frozen=True, slots=True)
class PlaybackFinished:
    """The browser has finished playing an utterance.

    The server cannot know this on its own: it knows when it *sent* the last
    chunk, not when the speaker fell silent. Waiting for this message is what
    keeps the examiner from talking over the tail of their own sentence.
    """

    utterance_id: int


@dataclass(frozen=True, slots=True)
class ClientError:
    """Something failed in the browser, most often microphone permission."""

    message: str


ClientMessage = AudioChunk | Hello | PlaybackFinished | ClientError


@dataclass(frozen=True, slots=True)
class Ready:
    """The server is ready for audio."""


@dataclass(frozen=True, slots=True)
class PhaseChanged:
    """The exam has moved to a new phase. Drives the browser's display."""

    phase: Phase


@dataclass(frozen=True, slots=True)
class UtteranceBegin:
    """Audio chunks for one examiner utterance are about to follow.

    Carries the text so the browser can show what was said -- useful while
    developing, and the basis of the accessibility view later.
    """

    utterance_id: int
    text: str


@dataclass(frozen=True, slots=True)
class UtteranceEnd:
    """No further audio belongs to this utterance.

    The browser replies with :class:`PlaybackFinished` once its queue drains.
    """

    utterance_id: int


@dataclass(frozen=True, slots=True)
class StopPlayback:
    """Discard queued examiner audio immediately: the candidate is speaking."""


@dataclass(frozen=True, slots=True)
class SessionEnd:
    """The exam is over."""

    reason: str


ServerEvent = Ready | PhaseChanged | UtteranceBegin | UtteranceEnd | StopPlayback | SessionEnd

_CLIENT_MESSAGES: dict[str, type] = {
    "hello": Hello,
    "playback_finished": PlaybackFinished,
    "client_error": ClientError,
}

_SERVER_EVENT_NAMES: dict[type, str] = {
    Ready: "ready",
    PhaseChanged: "phase",
    UtteranceBegin: "utterance_begin",
    UtteranceEnd: "utterance_end",
    StopPlayback: "stop_playback",
    SessionEnd: "session_end",
}


def encode(event: ServerEvent) -> str:
    """Serialise a server event to the JSON the browser expects."""
    payload: dict[str, Any] = {"type": _SERVER_EVENT_NAMES[type(event)]}
    payload.update({key: _plain(value) for key, value in asdict(event).items()})
    return json.dumps(payload)


def parse(text: str) -> ClientMessage:
    """Parse a JSON control message from the browser.

    Raises:
        ValueError: on malformed JSON or an unknown message type. The browser is
            our own code, so anything unexpected is a bug rather than input to
            tolerate.
    """
    try:
        payload = json.loads(text)
        message_type = _CLIENT_MESSAGES[payload.pop("type")]
    except (json.JSONDecodeError, KeyError, AttributeError) as error:
        raise ValueError(f"unrecognised client message: {text!r}") from error
    try:
        return message_type(**payload)  # type: ignore[no-any-return]
    except TypeError as error:
        raise ValueError(f"malformed client message: {text!r}") from error


def _plain(value: object) -> object:
    """Render enum members as their values, leaving everything else alone."""
    return value.value if isinstance(value, Phase) else value
