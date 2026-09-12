"""The turn-taking policy, as a table of cases.

Each row is a situation that can occur during a real exam and the behaviour the
examiner must show. When a threshold is retuned, this table is what says whether
the retuning broke something that used to work.
"""

import pytest

from ielts_examiner.config import DEFAULT_TURN_CONFIG
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision, TurnSignals
from ielts_examiner.turntaking.policy import decide, required_silence_ms


def signals(**overrides: object) -> TurnSignals:
    """A neutral set of signals, overridden field by field."""
    defaults: dict[str, object] = {
        "silence_ms": 0,
        "speech_ms": 0,
        "contiguous_speech_ms": 0,
        "phase_elapsed_ms": 0,
        "partial_transcript": "",
        "energy_slope": 0.0,
        "examiner_speaking": False,
    }
    return TurnSignals(**(defaults | overrides))  # type: ignore[arg-type]


CASES = [
    pytest.param(
        Phase.PART1,
        signals(speech_ms=3_000, silence_ms=750, partial_transcript="I live in Rome"),
        TurnDecision.ENDPOINT,
        id="part1-complete-answer-endpoints",
    ),
    pytest.param(
        Phase.PART1,
        signals(speech_ms=3_000, silence_ms=650, partial_transcript="I live in Rome"),
        TurnDecision.KEEP_LISTENING,
        id="part1-below-threshold-waits",
    ),
    pytest.param(
        Phase.PART1,
        signals(speech_ms=2_000, silence_ms=750, partial_transcript="I think um"),
        TurnDecision.KEEP_LISTENING,
        id="part1-filler-extends-past-threshold",
    ),
    pytest.param(
        Phase.PART1,
        signals(speech_ms=2_000, silence_ms=1_600, partial_transcript="I think um"),
        TurnDecision.ENDPOINT,
        id="part1-filler-extension-eventually-expires",
    ),
    pytest.param(
        Phase.PART1,
        signals(speech_ms=2_000, silence_ms=900, partial_transcript="I went to"),
        TurnDecision.KEEP_LISTENING,
        id="part1-dangling-preposition-extends",
    ),
    pytest.param(
        Phase.PART1,
        signals(speech_ms=0, silence_ms=5_000),
        TurnDecision.KEEP_LISTENING,
        id="part1-silence-before-any-speech-is-not-an-endpoint",
    ),
    # --- Part 2 long turn: the phase a conversational threshold would ruin ---
    pytest.param(
        Phase.PART2_LONG_TURN,
        signals(
            speech_ms=70_000,
            silence_ms=3_500,
            phase_elapsed_ms=75_000,
            partial_transcript="and",
        ),
        TurnDecision.KEEP_LISTENING,
        id="part2-hesitation-pause-does-not-interrupt",
    ),
    pytest.param(
        Phase.PART2_LONG_TURN,
        signals(
            speech_ms=70_000,
            silence_ms=4_200,
            phase_elapsed_ms=75_000,
            partial_transcript="that is all I wanted to say",
        ),
        TurnDecision.ENDPOINT,
        id="part2-long-pause-after-complete-phrase-ends-turn",
    ),
    pytest.param(
        Phase.PART2_LONG_TURN,
        signals(speech_ms=90_000, silence_ms=0, phase_elapsed_ms=120_001),
        TurnDecision.FORCE_STOP,
        id="part2-two-minute-cutoff-is-unconditional",
    ),
    pytest.param(
        Phase.PART2_LONG_TURN,
        signals(speech_ms=20_000, silence_ms=8_500, phase_elapsed_ms=30_000),
        TurnDecision.PROMPT_CONTINUE,
        id="part2-stalling-early-is-prompted-not-ended",
    ),
    pytest.param(
        Phase.PART2_LONG_TURN,
        signals(speech_ms=20_000, silence_ms=5_000, phase_elapsed_ms=30_000),
        TurnDecision.KEEP_LISTENING,
        id="part2-pause-below-expected-length-never-endpoints",
    ),
    pytest.param(
        Phase.PART2_PREP,
        signals(speech_ms=4_000, silence_ms=9_000, phase_elapsed_ms=30_000),
        TurnDecision.KEEP_LISTENING,
        id="part2-prep-ignores-the-microphone",
    ),
    pytest.param(
        Phase.PART2_PREP,
        signals(phase_elapsed_ms=60_000),
        TurnDecision.FORCE_STOP,
        id="part2-prep-ends-on-its-timer",
    ),
    # --- Barge-in and residual echo ---
    pytest.param(
        Phase.PART1,
        signals(examiner_speaking=True, contiguous_speech_ms=150, speech_ms=150),
        TurnDecision.KEEP_LISTENING,
        id="short-burst-over-examiner-is-treated-as-echo",
    ),
    pytest.param(
        Phase.PART1,
        signals(examiner_speaking=True, contiguous_speech_ms=350, speech_ms=350),
        TurnDecision.BARGE_IN,
        id="sustained-speech-over-examiner-is-a-real-interruption",
    ),
    pytest.param(
        Phase.PART2_LONG_TURN,
        signals(examiner_speaking=True, contiguous_speech_ms=900, phase_elapsed_ms=120_500),
        TurnDecision.FORCE_STOP,
        id="time-limit-outranks-barge-in",
    ),
    # --- Part 3 ---
    pytest.param(
        Phase.PART3,
        signals(speech_ms=8_000, silence_ms=900, partial_transcript="it depends on the country"),
        TurnDecision.KEEP_LISTENING,
        id="part3-tolerates-longer-thinking-pauses-than-part1",
    ),
    pytest.param(
        Phase.PART3,
        signals(speech_ms=8_000, silence_ms=1_200, partial_transcript="it depends on the country"),
        TurnDecision.ENDPOINT,
        id="part3-endpoints-past-its-own-threshold",
    ),
]


@pytest.mark.parametrize(("phase", "turn_signals", "expected"), CASES)
def test_decide(phase: Phase, turn_signals: TurnSignals, expected: TurnDecision) -> None:
    assert decide(turn_signals, phase) is expected


def test_settled_turn_shortens_the_wait_after_a_complete_phrase() -> None:
    tuning = DEFAULT_TURN_CONFIG.tuning_for(Phase.PART3)
    brief = signals(speech_ms=5_000, partial_transcript="yes I agree with that")
    settled = signals(speech_ms=40_000, partial_transcript="yes I agree with that")

    assert required_silence_ms(settled, tuning) < required_silence_ms(brief, tuning)


def test_falling_energy_shortens_the_wait() -> None:
    tuning = DEFAULT_TURN_CONFIG.tuning_for(Phase.PART1)
    steady = signals(partial_transcript="that is my opinion", energy_slope=0.0)
    trailing = signals(partial_transcript="that is my opinion", energy_slope=-0.4)

    assert required_silence_ms(trailing, tuning) < required_silence_ms(steady, tuning)


def test_adjustments_never_collapse_the_threshold() -> None:
    tuning = DEFAULT_TURN_CONFIG.tuning_for(Phase.PART1)
    every_reduction = signals(
        speech_ms=120_000, partial_transcript="that is my final answer.", energy_slope=-0.9
    )

    assert required_silence_ms(every_reduction, tuning) >= DEFAULT_TURN_CONFIG.min_silence_ms


def test_the_same_pause_is_read_differently_in_part1_and_part2() -> None:
    """The single most important property of the whole policy."""
    pause = signals(
        speech_ms=30_000, silence_ms=2_000, phase_elapsed_ms=70_000, partial_transcript="my friend"
    )

    assert decide(pause, Phase.PART1) is TurnDecision.ENDPOINT
    assert decide(pause, Phase.PART2_LONG_TURN) is TurnDecision.KEEP_LISTENING
