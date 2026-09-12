"""The turn-taking policy: one pure function, no state, no clock, no I/O.

This is the component that decides whether the examiner speaks or waits, and it
is the one most likely to be wrong on the first attempt. Keeping it pure is what
makes it cheap to be wrong: every case is a row in a test table, and replaying a
recorded session re-runs all of them for free.

Order matters. The checks below are arranged so that exactly one applies, from
the most peremptory (a hard time limit) to the most nuanced (a pause read
against the shape of the sentence it follows).
"""

from ielts_examiner.config import DEFAULT_TURN_CONFIG, PhaseTuning, TurnConfig
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision, TurnSignals
from ielts_examiner.turntaking.lexicon import Tail, classify_tail


def decide(
    signals: TurnSignals,
    phase: Phase,
    config: TurnConfig = DEFAULT_TURN_CONFIG,
) -> TurnDecision:
    """Decide what the runtime should do, given the state of the current turn.

    Args:
        signals: what has been observed since the phase began.
        phase: the phase in progress, which sets the thresholds.
        config: tuning values. Injected so tests can vary them explicitly.

    Returns:
        Exactly one decision. Never a combination.
    """
    tuning = config.tuning_for(phase)

    # A hard limit is not a suggestion. The examiner interrupting the candidate
    # at two minutes is not a failure mode, it is the exam working correctly.
    if _time_limit_expired(signals, tuning):
        return TurnDecision.FORCE_STOP

    # While the examiner is speaking the only open question is whether the
    # candidate is genuinely interrupting or the echo canceller is leaking.
    if signals.examiner_speaking:
        return (
            TurnDecision.BARGE_IN
            if signals.contiguous_speech_ms >= config.barge_in_guard_ms
            else TurnDecision.KEEP_LISTENING
        )

    if not phase.listens_to_candidate:
        return TurnDecision.KEEP_LISTENING

    # Below the expected length, a pause means the candidate has run dry rather
    # than finished. Ending the turn here would cut the Part 2 monologue short;
    # the examiner prompts instead.
    if _below_expected_length(signals, tuning):
        return (
            TurnDecision.PROMPT_CONTINUE
            if _idle_long_enough_to_prompt(signals, tuning)
            else TurnDecision.KEEP_LISTENING
        )

    # Silence before the candidate has said anything at all is the examiner's
    # own pause, not the end of an answer.
    if signals.speech_ms == 0:
        return TurnDecision.KEEP_LISTENING

    if signals.silence_ms >= required_silence_ms(signals, tuning, config):
        return TurnDecision.ENDPOINT
    return TurnDecision.KEEP_LISTENING


def required_silence_ms(
    signals: TurnSignals,
    tuning: PhaseTuning,
    config: TurnConfig = DEFAULT_TURN_CONFIG,
) -> int:
    """Pause length that ends the turn, adjusted for how the candidate is speaking.

    Exposed separately from :func:`decide` because it is the value worth logging
    and plotting when calibrating against replayed sessions: it explains *why* a
    turn ended where it did.

    Args:
        signals: state of the current turn.
        tuning: phase-specific thresholds.
        config: global adjustments.

    Returns:
        The required silence in milliseconds, never below ``config.min_silence_ms``.
    """
    tail = classify_tail(signals.partial_transcript)
    required = tuning.silence_threshold_ms

    # Grammar first: a sentence that cannot end here is worth waiting for.
    if tail is Tail.HESITATION:
        required += config.hesitation_extension_ms
    elif tail is Tail.DANGLING:
        required += config.dangling_extension_ms

    # A candidate well into a long answer who lands on a complete phrase has
    # almost certainly finished; waiting the full threshold just adds dead air.
    if tail is Tail.COMPLETE and signals.speech_ms >= config.settled_turn_ms:
        required -= config.settled_turn_reduction_ms

    # Audibly winding down is a prosodic hint that agrees with the grammar.
    if signals.energy_slope <= config.falling_energy_slope:
        required -= config.falling_energy_reduction_ms

    return max(required, config.min_silence_ms)


def _time_limit_expired(signals: TurnSignals, tuning: PhaseTuning) -> bool:
    """Whether the phase has run past its hard cap."""
    return tuning.time_limit_ms is not None and signals.phase_elapsed_ms >= tuning.time_limit_ms


def _below_expected_length(signals: TurnSignals, tuning: PhaseTuning) -> bool:
    """Whether the phase is too young for a pause to mean the turn is over."""
    return tuning.min_duration_ms is not None and signals.phase_elapsed_ms < tuning.min_duration_ms


def _idle_long_enough_to_prompt(signals: TurnSignals, tuning: PhaseTuning) -> bool:
    """Whether the candidate has been silent long enough to deserve a nudge."""
    return (
        tuning.idle_prompt_after_ms is not None
        and signals.silence_ms >= tuning.idle_prompt_after_ms
    )
