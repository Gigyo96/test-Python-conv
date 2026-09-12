"""Replaying a recording through the pipeline.

The exit criterion for milestone M1: a synthetic session can be replayed and the
decisions it produces are the ones the exam format calls for.
"""

from pathlib import Path

from ielts_examiner.audio.frames import iter_frames
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision
from ielts_examiner.replay import replay_frames, replay_wav
from tests.fixtures.synthetic_audio import build_pcm, write_wav

ANSWER_THEN_PAUSE = [("silence", 200), ("speech", 3_000), ("silence", 2_000)]


def replay(segments: list[tuple[str, int]], phase: Phase, **kwargs: object):
    return replay_frames(iter_frames(build_pcm(segments)), phase=phase, **kwargs)  # type: ignore[arg-type]


def test_a_short_answer_endpoints_in_part1() -> None:
    result = replay(ANSWER_THEN_PAUSE, Phase.PART1)

    endpoints = result.of_kind(TurnDecision.ENDPOINT)
    assert endpoints, "a 2 s pause after a complete answer must end the turn in Part 1"
    assert 3_800 <= endpoints[0].at_ms <= 4_200


def test_the_same_recording_does_not_endpoint_in_the_part2_long_turn() -> None:
    """The regression this whole design exists to prevent."""
    result = replay(ANSWER_THEN_PAUSE, Phase.PART2_LONG_TURN)

    assert not result.of_kind(TurnDecision.ENDPOINT)


def test_a_hesitation_pause_survives_the_long_turn() -> None:
    segments = [("speech", 40_000), ("silence", 3_500), ("speech", 30_000), ("silence", 5_000)]
    result = replay(segments, Phase.PART2_LONG_TURN)

    endpoints = result.of_kind(TurnDecision.ENDPOINT)
    assert endpoints, "the candidate did finish eventually"
    assert endpoints[0].at_ms > 70_000, "the mid-answer pause must not have ended the turn"


def test_the_two_minute_limit_stops_an_endless_answer() -> None:
    result = replay([("speech", 130_000)], Phase.PART2_LONG_TURN)

    stops = result.of_kind(TurnDecision.FORCE_STOP)
    assert stops
    assert 119_900 <= stops[0].at_ms <= 120_100


def test_stalling_early_in_the_long_turn_is_prompted() -> None:
    result = replay([("speech", 8_000), ("silence", 12_000)], Phase.PART2_LONG_TURN)

    assert result.of_kind(TurnDecision.PROMPT_CONTINUE)
    assert not result.of_kind(TurnDecision.ENDPOINT)


def test_a_trailing_transcript_delays_the_endpoint() -> None:
    without = replay(ANSWER_THEN_PAUSE, Phase.PART1)
    with_filler = replay(ANSWER_THEN_PAUSE, Phase.PART1, transcript_at=[(3_000, "I think um")])

    assert (
        with_filler.of_kind(TurnDecision.ENDPOINT)[0].at_ms
        > without.of_kind(TurnDecision.ENDPOINT)[0].at_ms
    )


def test_replay_is_deterministic() -> None:
    first = replay(ANSWER_THEN_PAUSE, Phase.PART1)
    second = replay(ANSWER_THEN_PAUSE, Phase.PART1)

    assert first.decisions == second.decisions


def test_replaying_a_wav_file_matches_replaying_its_frames(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "candidate.wav", ANSWER_THEN_PAUSE)

    assert (
        replay_wav(path, phase=Phase.PART1).decisions
        == replay(ANSWER_THEN_PAUSE, Phase.PART1).decisions
    )


def test_a_wav_in_the_wrong_format_is_refused(tmp_path: Path) -> None:
    import wave

    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44_100)
        handle.writeframes(bytes(4_000))

    import pytest

    with pytest.raises(ValueError, match="expected 16000 Hz mono"):
        replay_wav(path, phase=Phase.PART1)
