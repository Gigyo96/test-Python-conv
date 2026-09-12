"""Bookkeeping in the turn detector."""

from ielts_examiner.config import DEFAULT_TURN_CONFIG
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision
from ielts_examiner.turntaking.detector import TurnDetector

FRAME_MS = 20


def feed(
    detector: TurnDetector, *, is_speech: bool, duration_ms: int, start_ms: int, energy: float = 0.2
) -> int:
    """Push frames of one kind and return the session time after the last one."""
    at_ms = start_ms
    for _ in range(duration_ms // FRAME_MS):
        at_ms += FRAME_MS
        detector.observe(is_speech=is_speech, energy=energy if is_speech else 0.0, at_ms=at_ms)
    return at_ms


def test_silence_accumulates_only_after_speech_stops() -> None:
    detector = TurnDetector()
    detector.begin_phase(Phase.PART1, at_ms=0)

    at_ms = feed(detector, is_speech=True, duration_ms=1_000, start_ms=0)
    assert detector.signals(at_ms=at_ms).silence_ms == 0

    at_ms = feed(detector, is_speech=False, duration_ms=400, start_ms=at_ms)
    assert detector.signals(at_ms=at_ms).silence_ms == 400


def test_speech_resets_silence_but_keeps_the_total() -> None:
    detector = TurnDetector()
    detector.begin_phase(Phase.PART1, at_ms=0)

    at_ms = feed(detector, is_speech=True, duration_ms=600, start_ms=0)
    at_ms = feed(detector, is_speech=False, duration_ms=300, start_ms=at_ms)
    at_ms = feed(detector, is_speech=True, duration_ms=200, start_ms=at_ms)

    snapshot = detector.signals(at_ms=at_ms)
    assert snapshot.silence_ms == 0
    assert snapshot.speech_ms == 800


def test_endpoint_fires_once_the_pause_is_long_enough() -> None:
    detector = TurnDetector()
    detector.begin_phase(Phase.PART1, at_ms=0)
    at_ms = feed(detector, is_speech=True, duration_ms=2_000, start_ms=0)
    detector.update_transcript("I live in Rome")

    decisions = []
    for _ in range(50):  # 1 second of silence, past the 700 ms threshold
        at_ms += FRAME_MS
        decisions.append(detector.observe(is_speech=False, energy=0.0, at_ms=at_ms))

    assert TurnDecision.ENDPOINT in decisions


def test_phase_elapsed_is_measured_from_the_phase_start_not_the_session() -> None:
    detector = TurnDetector()
    detector.begin_phase(Phase.PART2_LONG_TURN, at_ms=400_000)

    assert detector.signals(at_ms=460_000).phase_elapsed_ms == 60_000


def test_new_turn_clears_counters_without_restarting_the_phase() -> None:
    detector = TurnDetector()
    detector.begin_phase(Phase.PART1, at_ms=0)
    at_ms = feed(detector, is_speech=True, duration_ms=1_000, start_ms=0)

    detector.start_new_turn()

    snapshot = detector.signals(at_ms=at_ms)
    assert snapshot.speech_ms == 0
    assert snapshot.phase_elapsed_ms == at_ms


def test_echo_during_playback_cannot_carry_into_a_later_barge_in() -> None:
    """A speech run picked up while the examiner spoke is discarded on release."""
    detector = TurnDetector()
    detector.begin_phase(Phase.PART1, at_ms=0)
    detector.set_examiner_speaking(True)
    at_ms = feed(detector, is_speech=True, duration_ms=200, start_ms=0)

    detector.set_examiner_speaking(False)

    assert detector.signals(at_ms=at_ms).contiguous_speech_ms == 0


def test_the_vad_hangover_does_not_fake_a_falling_slope() -> None:
    """Regression: near-silent release frames must not look like winding down.

    The detector keeps reporting speech for a few frames after the voice stops.
    Those frames used to enter the energy window and drag the slope to -1 at the
    end of every single turn, firing the prosodic hint for the wrong reason.
    """
    detector = TurnDetector()
    detector.begin_phase(Phase.PART1, at_ms=0)

    at_ms = 0
    for step, energy in enumerate([0.20] * 10 + [0.001, 0.001, 0.001], start=1):
        at_ms = step * FRAME_MS
        detector.observe(is_speech=True, energy=energy, at_ms=at_ms)

    assert detector.signals(at_ms=at_ms).energy_slope > DEFAULT_TURN_CONFIG.falling_energy_slope


def test_energy_slope_is_negative_while_trailing_off() -> None:
    detector = TurnDetector()
    detector.begin_phase(Phase.PART1, at_ms=0)

    at_ms = 0
    for step, energy in enumerate([0.30, 0.25, 0.20, 0.15, 0.10, 0.05], start=1):
        at_ms = step * FRAME_MS
        detector.observe(is_speech=True, energy=energy, at_ms=at_ms)

    assert detector.signals(at_ms=at_ms).energy_slope < DEFAULT_TURN_CONFIG.falling_energy_slope
