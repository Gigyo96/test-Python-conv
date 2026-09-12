"""Tuning knobs for the exam runtime.

Everything in this module is data. Keeping the thresholds out of the code that
uses them is what allows the turn-taking policy to stay a pure function of
``(signals, phase, config)`` -- and therefore to be tuned from a table of
regression cases instead of by talking into a microphone.

The values below are *reasoned, not measured*. They are the starting point for
the replay-driven calibration described in ``docs/ARCHITECTURE.md`` (section 4).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ielts_examiner.domain.phase import Phase


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Identity of the examiner's voice.

    One profile is used for the whole session, for both cached and live speech:
    any difference in voice or rate between the two is audible at the seam and
    breaks the illusion of a single person conducting the exam.
    """

    name: str
    language_code: str = "en-GB"
    speaking_rate: float = 1.0
    pitch: float = 0.0


@dataclass(frozen=True, slots=True)
class PhaseTuning:
    """How the examiner behaves during one phase."""

    silence_threshold_ms: int
    """Base pause length that ends the candidate's turn, before adjustments."""

    response_delay_ms: int = 600
    """Pause the examiner takes before speaking.

    Counter-intuitively this makes the exam feel *more* real, not less: a human
    examiner annotates the assessment form for a second or two between answers.
    """

    time_limit_ms: int | None = None
    """Hard cap on the phase. When it expires the examiner takes the floor."""

    min_duration_ms: int | None = None
    """Length below which a pause means "stalled", not "finished".

    Only meaningful for the Part 2 long turn, where a candidate who stops after
    thirty seconds has not answered the question -- they have run dry, and the
    examiner prompts them rather than moving on.
    """

    idle_prompt_after_ms: int | None = None
    """Silence that triggers a prompt while below ``min_duration_ms``."""


@dataclass(frozen=True, slots=True)
class TurnConfig:
    """Complete turn-taking configuration.

    Phase-specific values live in ``phases``; the adjustments below are global
    because they describe how people speak, not how the exam is structured.
    """

    phases: Mapping[Phase, PhaseTuning]

    hesitation_extension_ms: int = 800
    """Added when the transcript trails off into a filler ("um", "I mean")."""

    dangling_extension_ms: int = 500
    """Added when the transcript ends mid-construction ("because", "to")."""

    settled_turn_ms: int = 25_000
    """Speech length past which a clean ending can be trusted sooner."""

    settled_turn_reduction_ms: int = 200
    """Subtracted once the turn is settled and ends on a complete phrase."""

    falling_energy_slope: float = -0.15
    """Relative energy drop that counts as trailing off (15% across the window)."""

    falling_energy_reduction_ms: int = 150
    """Subtracted when the candidate is audibly winding down."""

    barge_in_guard_ms: int = 300
    """Sustained speech required to interrupt the examiner.

    The browser's echo canceller is good but not perfect at high speaker volume.
    Residual echo is low-energy and fragmented, so requiring a sustained run is
    a cheap second line of defence. The cost is 300 ms of latency on a real
    interruption, which is invisible -- a human examiner does not fall silent
    instantly either.
    """

    min_silence_ms: int = 250
    """Floor for the adjusted threshold, so reductions can never stack into zero."""

    def tuning_for(self, phase: Phase) -> PhaseTuning:
        """Return the tuning for ``phase``.

        Raises:
            KeyError: if the phase has no tuning, which is a configuration bug
                rather than a runtime condition worth recovering from.
        """
        return self.phases[phase]


DEFAULT_PHASE_TUNING: Mapping[Phase, PhaseTuning] = MappingProxyType(
    {
        Phase.INTRO: PhaseTuning(silence_threshold_ms=700, response_delay_ms=500),
        Phase.PART1: PhaseTuning(silence_threshold_ms=700, response_delay_ms=600),
        # The preparation minute is silent by construction: the threshold is
        # never consulted because the phase does not listen to the candidate.
        Phase.PART2_PREP: PhaseTuning(
            silence_threshold_ms=0,
            response_delay_ms=0,
            time_limit_ms=60_000,
        ),
        # Four seconds is long enough to survive the hesitation pauses of an
        # unrehearsed two-minute monologue, which a conversational 700 ms
        # threshold would shred.
        Phase.PART2_LONG_TURN: PhaseTuning(
            silence_threshold_ms=4_000,
            response_delay_ms=400,
            time_limit_ms=120_000,
            min_duration_ms=60_000,
            idle_prompt_after_ms=8_000,
        ),
        Phase.PART2_ROUNDING: PhaseTuning(silence_threshold_ms=800, response_delay_ms=600),
        # Part 3 answers are abstract and full of thinking pauses.
        Phase.PART3: PhaseTuning(silence_threshold_ms=1_100, response_delay_ms=1_000),
        Phase.CLOSING: PhaseTuning(silence_threshold_ms=700, response_delay_ms=500),
    }
)

DEFAULT_TURN_CONFIG = TurnConfig(phases=DEFAULT_PHASE_TUNING)
