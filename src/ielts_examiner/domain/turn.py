"""Inputs and outputs of the turn-taking policy."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class TurnSignals:
    """Everything the policy is allowed to look at when deciding a turn.

    Deliberately flat and boring: no audio buffers, no clients, no clock. A
    caller can build one by hand in a test, which is the whole point.
    """

    silence_ms: int
    """Time since the candidate last produced speech. Zero while speaking."""

    speech_ms: int
    """Total candidate speech accumulated in the current turn."""

    contiguous_speech_ms: int
    """Length of the current uninterrupted speech run.

    Separate from ``speech_ms`` because the two answer different questions: the
    barge-in guard needs to know whether the candidate is *sustaining* speech
    over the examiner (residual echo is short and fragmented), while the
    settled-turn rule cares about how much has been said overall.
    """

    phase_elapsed_ms: int
    """Time since the current phase began. Drives the hard time limits."""

    partial_transcript: str
    """Best-effort transcript of the turn so far, used for semantic endpointing.

    May be empty when the recogniser has not caught up yet; the policy treats an
    empty transcript as carrying no information rather than as a signal.
    """

    energy_slope: float
    """Relative change in speech energy across the trailing window.

    Negative means the candidate is trailing off, a prosodic hint that the turn
    is ending. See ``turntaking.detector`` for how it is computed.
    """

    examiner_speaking: bool
    """Whether the examiner's audio is currently playing."""


class TurnDecision(StrEnum):
    """What the runtime should do next.

    Exactly one of these is returned per observation, so the caller never has to
    reconcile overlapping outcomes.
    """

    KEEP_LISTENING = "keep_listening"
    """Nothing to do. The overwhelmingly common answer."""

    ENDPOINT = "endpoint"
    """The candidate has finished. The examiner may take the floor."""

    BARGE_IN = "barge_in"
    """The candidate is talking over the examiner: stop the playback."""

    FORCE_STOP = "force_stop"
    """A hard time limit expired and the examiner takes the floor unconditionally.

    This is the Part 2 two-minute cut-off, and the end of the preparation minute.
    """

    PROMPT_CONTINUE = "prompt_continue"
    """The candidate stalled well before the expected length: nudge them."""
