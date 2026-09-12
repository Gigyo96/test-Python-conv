"""The debouncing state machine shared by both detectors."""

from ielts_examiner.audio.hysteresis import SpeechGate


def gate(**overrides: float | int) -> SpeechGate:
    defaults: dict = {"activation": 0.5, "deactivation": 0.3, "hangover_ms": 100}
    return SpeechGate(**(defaults | overrides))  # type: ignore[arg-type]


def test_speech_starts_only_above_the_activation_threshold() -> None:
    speech = gate()

    assert speech.update(0.4, elapsed_ms=20) is False
    assert speech.update(0.6, elapsed_ms=20) is True


def test_a_level_between_the_thresholds_sustains_but_does_not_start() -> None:
    """The reason there are two thresholds: no oscillation in the grey zone."""
    speech = gate()

    assert speech.update(0.4, elapsed_ms=20) is False
    speech.update(0.6, elapsed_ms=20)
    assert speech.update(0.4, elapsed_ms=20) is True


def test_release_waits_out_the_hangover() -> None:
    speech = gate(hangover_ms=100)
    speech.update(0.9, elapsed_ms=20)

    assert speech.update(0.0, elapsed_ms=60) is True
    assert speech.update(0.0, elapsed_ms=60) is False


def test_a_blip_above_the_deactivation_level_restarts_the_hangover() -> None:
    speech = gate(hangover_ms=100)
    speech.update(0.9, elapsed_ms=20)
    speech.update(0.0, elapsed_ms=80)

    assert speech.update(0.35, elapsed_ms=20) is True
    assert speech.update(0.0, elapsed_ms=80) is True


def test_reset_forgets_the_run() -> None:
    speech = gate()
    speech.update(0.9, elapsed_ms=20)

    speech.reset()

    assert speech.active is False
