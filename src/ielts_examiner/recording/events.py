"""Append-only event log, one JSON object per line.

Two properties are worth the format's verbosity. It is *durable*: every append
is flushed, so a session that dies mid-exam still yields everything up to the
failure. And it is *replayable*: the log plus the recorded audio is enough to
re-run the pipeline without the candidate present.

Events carry a free-form payload rather than one dataclass per kind. That is a
considered trade-off: the log is written by many call sites and read by tools
that must tolerate older sessions, so a rigid schema would age badly. The
discipline lives in :class:`EventKind`, which is closed.
"""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TextIO


class EventKind(StrEnum):
    """Every kind of event the runtime may record."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"

    PHASE_ENTER = "phase_enter"
    PHASE_EXIT = "phase_exit"

    EXAMINER_UTTERANCE = "examiner_utterance"
    """What the examiner said, and whether it came from the pre-synthesis cache."""

    CANDIDATE_SPEECH_START = "candidate_speech_start"
    CANDIDATE_SPEECH_END = "candidate_speech_end"

    STT_PARTIAL = "stt_partial"
    STT_FINAL = "stt_final"

    TURN_DECISION = "turn_decision"
    """A decision other than ``keep_listening``, with the signals behind it.

    Logging the signals alongside the outcome is what makes calibration possible
    after the fact: a wrong endpoint can be explained rather than guessed at.
    """

    TIMER_FIRED = "timer_fired"
    BARGE_IN = "barge_in"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Event:
    """One recorded moment."""

    kind: EventKind
    at_ms: int
    """Session time, milliseconds from the start of the recording."""

    data: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialise to a single line of JSON."""
        return json.dumps(
            {"kind": str(self.kind), "at_ms": self.at_ms, "data": dict(self.data)},
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, line: str) -> "Event":
        """Parse a line written by :meth:`to_json`.

        Raises:
            ValueError: if the line is malformed or names an unknown event kind.
        """
        try:
            raw = json.loads(line)
            return cls(kind=EventKind(raw["kind"]), at_ms=int(raw["at_ms"]), data=raw["data"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"malformed event line: {line!r}") from error


class EventLog:
    """Writes events to a JSONL file, flushing each one.

    Use as a context manager:

        with EventLog(paths.events) as log:
            log.append(EventKind.PHASE_ENTER, at_ms=0, phase="part1")
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._file: TextIO = path.open("a", encoding="utf-8")

    def append(self, kind: EventKind, *, at_ms: int, **data: Any) -> Event:
        """Record an event and flush it to disk.

        Flushing on every append costs a syscall per event -- a few hundred over
        a whole exam -- and buys durability, which is the reason the log exists.

        Returns:
            The event as written, so callers can log or assert on it.
        """
        event = Event(kind=kind, at_ms=at_ms, data=data)
        self._file.write(event.to_json() + "\n")
        self._file.flush()
        return event

    def close(self) -> None:
        """Close the underlying file."""
        self._file.close()

    def __enter__(self) -> Self:
        """Enter the context, returning the open log."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the log, whether or not the session ended cleanly."""
        self.close()


def read_events(path: Path) -> Iterator[Event]:
    """Read a log back, skipping blank lines.

    Args:
        path: the JSONL file to read.

    Yields:
        Events in the order they were written.

    Raises:
        ValueError: on the first malformed line. A corrupt log is a bug worth
            surfacing, not data worth silently dropping.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield Event.from_json(line)
