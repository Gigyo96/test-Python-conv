"""Audio framing and voice activity detection."""

from ielts_examiner.audio.frames import FRAME_MS, SAMPLES_PER_FRAME, iter_frames
from ielts_examiner.audio.vad import EnergyVad
from tests.fixtures.synthetic_audio import build_pcm


def test_frames_are_consecutive_and_correctly_sized() -> None:
    frames = list(iter_frames(build_pcm([("speech", 100)])))

    assert len(frames) == 5
    assert all(frame.samples.size == SAMPLES_PER_FRAME for frame in frames)
    assert [frame.at_ms for frame in frames] == [0, 20, 40, 60, 80]


def test_a_trailing_partial_frame_is_dropped_not_padded() -> None:
    """Padding would fabricate a pause the candidate never took."""
    pcm = build_pcm([("speech", 100)])[: SAMPLES_PER_FRAME * 2 * 2 + 10]

    assert len(list(iter_frames(pcm))) == 2


def test_rms_separates_speech_from_the_noise_floor() -> None:
    speech = next(iter_frames(build_pcm([("speech", 100)])))
    silence = next(iter_frames(build_pcm([("silence", 100)])))

    assert speech.rms > silence.rms * 10


def test_vad_detects_speech_and_releases_after_the_hangover() -> None:
    vad = EnergyVad()
    verdicts = [
        vad.is_speech(frame)
        for frame in iter_frames(build_pcm([("speech", 200), ("silence", 400)]))
    ]

    assert any(verdicts[:10]), "speech must be detected"
    assert not verdicts[-1], "the detector must release during sustained silence"


def test_vad_release_is_delayed_by_at_most_the_hangover() -> None:
    hangover_ms = 60
    vad = EnergyVad(hangover_ms=hangover_ms)
    frames = list(iter_frames(build_pcm([("speech", 200), ("silence", 400)])))
    verdicts = [vad.is_speech(frame) for frame in frames]

    last_speech_index = max(index for index, verdict in enumerate(verdicts) if verdict)
    overshoot_ms = (last_speech_index + 1) * FRAME_MS - 200
    assert 0 <= overshoot_ms <= hangover_ms + FRAME_MS


def test_reset_forgets_the_current_run() -> None:
    vad = EnergyVad()
    frames = list(iter_frames(build_pcm([("speech", 200)])))
    for frame in frames:
        vad.is_speech(frame)

    vad.reset()

    silence = next(iter_frames(build_pcm([("silence", 100)])))
    assert not vad.is_speech(silence)
