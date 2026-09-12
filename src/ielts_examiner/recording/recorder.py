"""Writing one session to disk.

A thin facade over the event log and the two audio tracks. It exists so the
session runner holds one collaborator instead of three, and so the rule that
everything lands in one self-contained directory is stated in a single place.
"""

from types import TracebackType
from typing import Any, Self

from ielts_examiner.recording.audio_writer import WavWriter
from ielts_examiner.recording.events import EventKind, EventLog
from ielts_examiner.recording.session import SessionPaths


class SessionRecorder:
    """Records events and both audio tracks of one exam."""

    def __init__(self, paths: SessionPaths) -> None:
        self.paths = paths
        self._events = EventLog(paths.events)
        self._candidate = WavWriter(paths.candidate_audio)
        self._examiner = WavWriter(paths.examiner_audio)

    def event(self, kind: EventKind, *, at_ms: int, **data: Any) -> None:
        """Record one event."""
        self._events.append(kind, at_ms=at_ms, **data)

    def candidate_audio(self, pcm: bytes) -> None:
        """Append microphone audio.

        Kept even while the examiner is speaking: a recording with holes in it
        could not be replayed, and replay is how the endpointing gets calibrated.
        """
        self._candidate.write(pcm)

    def examiner_audio(self, pcm: bytes) -> None:
        """Append synthesised examiner audio."""
        self._examiner.write(pcm)

    def close(self) -> None:
        """Finalise every file."""
        self._events.close()
        self._candidate.close()
        self._examiner.close()

    def __enter__(self) -> Self:
        """Enter the context, returning the open recorder."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Finalise every file, whether or not the session ended cleanly."""
        self.close()
