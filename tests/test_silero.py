"""Windowing and debouncing around the Silero model."""

from pathlib import Path

import pytest

from ielts_examiner.audio.frames import FRAME_MS, iter_frames
from ielts_examiner.audio.hysteresis import SpeechGate
from ielts_examiner.audio.silero import WINDOW_MS, WINDOW_SAMPLES, SileroVad
from tests.fixtures.silero_stub import StubProbabilityModel
from tests.fixtures.synthetic_audio import build_pcm

FRAMES_PER_WINDOW = WINDOW_SAMPLES / (FRAME_MS * 16)  # 512 / 320 = 1.6


def frames(duration_ms: int) -> list:
    return list(iter_frames(build_pcm([("speech", duration_ms)])))


def test_frames_are_buffered_into_windows_of_the_size_the_model_expects() -> None:
    model = StubProbabilityModel()
    vad = SileroVad(model)

    for frame in frames(1_000):  # 50 frames of 320 samples = 16000 samples
        vad.is_speech(frame)

    assert model.windows == [WINDOW_SAMPLES] * (16_000 // WINDOW_SAMPLES)


def test_a_verdict_is_held_between_windows() -> None:
    """A 20 ms frame is shorter than the model's window, so verdicts persist.

    320 samples arrive per frame and the model consumes 512: the first frame
    completes no window, the second completes one, the third completes none
    again and must keep the verdict the second one produced.
    """
    model = StubProbabilityModel(probabilities=[0.9])
    vad = SileroVad(model)
    captured = [vad.is_speech(frame) for frame in frames(60)]

    assert captured == [False, True, True]
    assert len(model.windows) == 1, "only one window was complete across three frames"


def test_speech_ends_only_after_the_hangover() -> None:
    model = StubProbabilityModel(probabilities=[0.9] + [0.0] * 20)
    vad = SileroVad(model, hangover_ms=WINDOW_MS * 3)
    captured = [vad.is_speech(frame) for frame in frames(1_000)]

    assert True in captured and False in captured[captured.index(True) :]


def test_reset_clears_buffered_samples_and_the_verdict() -> None:
    model = StubProbabilityModel(probabilities=[0.9])
    vad = SileroVad(model)
    for frame in frames(200):
        vad.is_speech(frame)

    vad.reset()
    model.windows.clear()

    assert vad.is_speech(frames(20)[0]) is False
    assert model.windows == [], "partial samples must not survive a reset"


def test_a_gate_that_could_oscillate_is_refused() -> None:
    with pytest.raises(ValueError, match="deactivation"):
        SpeechGate(activation=0.3, deactivation=0.8, hangover_ms=100)


def test_the_missing_model_says_how_to_get_it(tmp_path: Path) -> None:
    """Degrading silently to a cruder detector would change how the exam listens."""
    with pytest.raises(FileNotFoundError, match="curl"):
        SileroVad.load(tmp_path / "absent.onnx")
