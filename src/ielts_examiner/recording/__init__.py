"""Durable record of a session.

The event log is the single source of truth (decision D10 in the architecture
document). Everything else -- the assessment, the report, a replay -- is derived
from it, which is what makes the assessment re-runnable offline and a crash
mid-exam survivable.
"""

from ielts_examiner.recording.audio_writer import WavWriter
from ielts_examiner.recording.events import Event, EventKind, EventLog, read_events
from ielts_examiner.recording.recorder import SessionRecorder
from ielts_examiner.recording.session import SessionPaths

__all__ = [
    "Event",
    "EventKind",
    "EventLog",
    "SessionPaths",
    "SessionRecorder",
    "WavWriter",
    "read_events",
]
