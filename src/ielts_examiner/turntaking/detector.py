"""Bookkeeping between the audio stream and the turn-taking policy.

This class holds all the mutable state of turn detection so that
``turntaking.policy`` can hold none. It counts milliseconds and remembers the
last transcript; every judgement is delegated.
"""

from collections import deque

from ielts_examiner.audio.frames import FRAME_MS
from ielts_examiner.config import DEFAULT_TURN_CONFIG, TurnConfig
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision, TurnSignals
from ielts_examiner.turntaking.policy import decide

_ENERGY_WINDOW_MS = 500
"""Trailing window over which the energy slope is measured.

Long enough to see a sentence wind down, short enough not to be dominated by the
start of the utterance.
"""

_VOICE_FLOOR_FRACTION = 0.10
"""Share of the window's peak below which a frame is not treated as voice.

The detector releases a few frames after speech actually stops (see
``audio.vad``), so the tail of every utterance carries near-silent frames that
the voice activity detector still reports as speech. Left in, they would drag
the slope to -1 at the end of *every* turn and the prosodic hint would fire for
the wrong reason -- detecting the hangover rather than the candidate winding
down.

Expressed as a fraction of the window's own peak rather than an absolute level,
so it holds for a quiet speaker and a loud one alike. The fraction is low on
purpose: genuine trailing off lands around a fifth to a half of peak and must
survive the filter, while hangover frames sit near zero and must not.
"""

_MIN_ENERGY = 1e-6
"""Floor for the slope denominator, so near-silence cannot produce a huge ratio."""


class TurnDetector:
    """Turns a stream of frame observations into turn-taking decisions.

    Typical use, once per audio frame:

        detector.begin_phase(Phase.PART1, at_ms=clock)
        ...
        decision = detector.observe(is_speech=vad.is_speech(frame), energy=frame.rms,
                                    at_ms=frame.at_ms)

    Timing is derived from the ``at_ms`` the caller supplies rather than from a
    wall clock, so a recorded session replays identically and eight times faster.
    """

    def __init__(self, config: TurnConfig = DEFAULT_TURN_CONFIG) -> None:
        self._config = config
        self._phase = Phase.INTRO
        self._phase_started_ms = 0
        self._examiner_speaking = False
        self._partial_transcript = ""
        self._silence_ms = 0
        self._speech_ms = 0
        self._contiguous_speech_ms = 0
        self._energies: deque[float] = deque(maxlen=_ENERGY_WINDOW_MS // FRAME_MS)

    def begin_phase(self, phase: Phase, *, at_ms: int) -> None:
        """Enter ``phase`` and reset every per-turn counter.

        Args:
            phase: the phase being entered.
            at_ms: session time at which it begins.
        """
        self._phase = phase
        self._phase_started_ms = at_ms
        self._reset_turn_counters()

    def set_examiner_speaking(self, speaking: bool) -> None:
        """Record whether the examiner's audio is playing.

        Ending playback also clears the speech run, so that echo picked up while
        the examiner spoke cannot be counted towards a later barge-in.
        """
        if self._examiner_speaking and not speaking:
            self._contiguous_speech_ms = 0
        self._examiner_speaking = speaking

    def update_transcript(self, partial: str) -> None:
        """Replace the partial transcript used for semantic endpointing."""
        self._partial_transcript = partial

    def observe(
        self,
        *,
        is_speech: bool,
        energy: float,
        at_ms: int,
        duration_ms: int = FRAME_MS,
    ) -> TurnDecision:
        """Account for one frame and decide what to do.

        Each observation contributes its own duration, so no audio is lost at a
        phase boundary and the totals do not lag the stream by a frame.

        Args:
            is_speech: the voice activity verdict for this frame.
            energy: normalised RMS of the frame, for the prosodic hint.
            at_ms: session time at which the frame starts.
            duration_ms: length of the frame.

        Returns:
            The decision for this instant.
        """
        if is_speech:
            self._speech_ms += duration_ms
            self._contiguous_speech_ms += duration_ms
            self._silence_ms = 0
            self._energies.append(energy)
        else:
            self._silence_ms += duration_ms
            self._contiguous_speech_ms = 0
        return decide(self.signals(at_ms=at_ms), self._phase, self._config)

    def start_new_turn(self) -> None:
        """Reset the counters without leaving the phase.

        Part 1 and Part 3 hold several question-answer turns inside one phase;
        the phase clock keeps running for budget purposes while the turn state
        starts over.
        """
        self._reset_turn_counters()

    def signals(self, *, at_ms: int) -> TurnSignals:
        """Snapshot of what the policy will see, useful for logging and tests."""
        return TurnSignals(
            silence_ms=self._silence_ms,
            speech_ms=self._speech_ms,
            contiguous_speech_ms=self._contiguous_speech_ms,
            phase_elapsed_ms=at_ms - self._phase_started_ms,
            partial_transcript=self._partial_transcript,
            energy_slope=self._energy_slope(),
            examiner_speaking=self._examiner_speaking,
        )

    def _reset_turn_counters(self) -> None:
        """Clear everything that describes the current turn."""
        self._silence_ms = 0
        self._speech_ms = 0
        self._contiguous_speech_ms = 0
        self._partial_transcript = ""
        self._energies.clear()

    def _energy_slope(self) -> float:
        """Relative change in speech energy across the trailing window.

        Expressed as a fraction of the window's opening energy, so it is
        independent of how loud the candidate is: ``-0.15`` means the voice is
        15% quieter than it was half a second ago, whether they whisper or boom.

        Frames below ``_VOICE_FLOOR_FRACTION`` of the window's peak are ignored,
        for the reason documented on that constant.
        """
        voiced = self._voiced_energies()
        if len(voiced) < 2:
            return 0.0
        first = max(voiced[0], _MIN_ENERGY)
        return (voiced[-1] - first) / first

    def _voiced_energies(self) -> list[float]:
        """Window frames loud enough to carry voice, in order."""
        if not self._energies:
            return []
        floor = max(self._energies) * _VOICE_FLOOR_FRACTION
        return [energy for energy in self._energies if energy >= floor]
