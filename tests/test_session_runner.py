"""The exam loop, driven end to end without a socket or a browser.

Every collaborator is real except the transport and the voice: the same turn
detector, policy and recorder that run in production. What is exercised here is
the orchestration -- who speaks when, what reaches the recording, and how the
loop reacts to an interruption or a disconnect.
"""

import asyncio
from pathlib import Path

import pytest

from ielts_examiner.audio.vad import EnergyVad
from ielts_examiner.config import DEFAULT_PHASE_TUNING, TurnConfig, VoiceProfile
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision
from ielts_examiner.recording.events import EventKind, read_events
from ielts_examiner.recording.recorder import SessionRecorder
from ielts_examiner.recording.session import SessionPaths
from ielts_examiner.server.driver import ScriptedExamDriver
from ielts_examiner.server.protocol import ClientError, PhaseChanged, SessionEnd, StopPlayback
from ielts_examiner.server.session_runner import BrowserError, SessionRunner
from ielts_examiner.services.fakes import SilentTextToSpeech
from tests.fixtures.synthetic_audio import build_pcm
from tests.fixtures.transport import FakeTransport, audio_frames

VOICE = VoiceProfile(name="test-voice")

INSTANT_CONFIG = TurnConfig(
    phases={
        phase: type(tuning)(
            silence_threshold_ms=tuning.silence_threshold_ms,
            response_delay_ms=0,  # the deliberate pause would only slow the suite
            time_limit_ms=tuning.time_limit_ms,
            min_duration_ms=tuning.min_duration_ms,
            idle_prompt_after_ms=tuning.idle_prompt_after_ms,
        )
        for phase, tuning in DEFAULT_PHASE_TUNING.items()
    }
)

ONE_ANSWER = build_pcm([("speech", 1_500), ("silence", 1_500)])


def run_session(
    tmp_path: Path,
    *,
    script: list,
    questions: list[str],
    closing: str = "Thank you.",
) -> tuple[FakeTransport, ScriptedExamDriver, SessionPaths]:
    """Run one session to completion and return what can be asserted on."""
    transport = FakeTransport(script)
    driver = ScriptedExamDriver(questions, closing, phase=Phase.PART1)
    paths = SessionPaths.create(tmp_path, session_id="exam")
    runner = SessionRunner(
        transport=transport,
        driver=driver,
        vad=EnergyVad(),
        tts=SilentTextToSpeech(),
        recorder=SessionRecorder(paths),
        voice=VOICE,
        config=INSTANT_CONFIG,
    )
    asyncio.run(runner.run())
    return transport, driver, paths


def test_the_examiner_asks_listens_and_closes(tmp_path: Path) -> None:
    transport, driver, _ = run_session(
        tmp_path,
        script=audio_frames(ONE_ANSWER) * 2,
        questions=["What is your name?", "Where do you live?"],
        closing="Thank you. That is the end of the speaking test.",
    )

    assert transport.spoken_text() == [
        "What is your name?",
        "Where do you live?",
        "Thank you. That is the end of the speaking test.",
    ]
    assert [outcome.decision for outcome in driver.outcomes] == [TurnDecision.ENDPOINT] * 2


def test_the_closing_formula_does_not_wait_for_an_answer(tmp_path: Path) -> None:
    """An announcement ends the exam; listening after it would hang."""
    transport, _, _ = run_session(
        tmp_path, script=audio_frames(ONE_ANSWER), questions=["Your name?"]
    )

    assert isinstance(transport.events[-1], SessionEnd)


def test_the_phase_reaches_the_browser_once(tmp_path: Path) -> None:
    transport, _, _ = run_session(
        tmp_path, script=audio_frames(ONE_ANSWER), questions=["Your name?"]
    )

    phases = [event for event in transport.events if isinstance(event, PhaseChanged)]
    assert phases == [PhaseChanged(phase=Phase.PART1)]


def test_the_turn_reports_how_much_the_candidate_spoke(tmp_path: Path) -> None:
    _, driver, _ = run_session(tmp_path, script=audio_frames(ONE_ANSWER), questions=["Your name?"])

    assert 1_400 <= driver.outcomes[0].speech_ms <= 1_700


def test_the_session_is_recorded_in_full(tmp_path: Path) -> None:
    _, _, paths = run_session(tmp_path, script=audio_frames(ONE_ANSWER), questions=["Your name?"])

    kinds = [event.kind for event in read_events(paths.events)]
    assert EventKind.SESSION_START in kinds
    assert EventKind.PHASE_ENTER in kinds
    assert EventKind.EXAMINER_UTTERANCE in kinds
    assert EventKind.TURN_DECISION in kinds
    assert EventKind.SESSION_END in kinds
    assert paths.candidate_audio.stat().st_size > 0
    assert paths.examiner_audio.stat().st_size > 0


def test_the_recorded_audio_can_be_replayed(tmp_path: Path) -> None:
    """The point of recording: a real session feeds the calibration loop."""
    from ielts_examiner.replay import replay_wav

    _, _, paths = run_session(tmp_path, script=audio_frames(ONE_ANSWER), questions=["Your name?"])
    result = replay_wav(paths.candidate_audio, phase=Phase.PART1)

    assert result.of_kind(TurnDecision.ENDPOINT)


def test_a_decision_event_records_the_signals_behind_it(tmp_path: Path) -> None:
    """Calibration needs the why, not just the what."""
    _, _, paths = run_session(tmp_path, script=audio_frames(ONE_ANSWER), questions=["Your name?"])

    decisions = [e for e in read_events(paths.events) if e.kind is EventKind.TURN_DECISION]
    assert decisions
    assert set(decisions[0].data) >= {"decision", "silence_ms", "speech_ms", "phase_elapsed_ms"}


def test_speaking_over_the_examiner_stops_the_playback(tmp_path: Path) -> None:
    """The candidate interrupts before the examiner's audio is acknowledged."""
    transport = FakeTransport(
        audio_frames(build_pcm([("speech", 1_000)])), acknowledge_playback=False
    )
    paths = SessionPaths.create(tmp_path, session_id="barge-in")
    runner = SessionRunner(
        transport=transport,
        driver=ScriptedExamDriver(["A long question."], "Thank you.", phase=Phase.PART1),
        vad=EnergyVad(),
        tts=SilentTextToSpeech(),
        recorder=SessionRecorder(paths),
        voice=VOICE,
        config=INSTANT_CONFIG,
    )

    with pytest.raises(BrowserError):
        asyncio.run(runner.run())

    assert any(isinstance(event, StopPlayback) for event in transport.events)


def test_a_client_failure_stops_the_exam(tmp_path: Path) -> None:
    transport = FakeTransport([ClientError(message="microphone permission denied")])
    paths = SessionPaths.create(tmp_path, session_id="failed")
    runner = SessionRunner(
        transport=transport,
        driver=ScriptedExamDriver(["Your name?"], "Thank you.", phase=Phase.PART1),
        vad=EnergyVad(),
        tts=SilentTextToSpeech(),
        recorder=SessionRecorder(paths),
        voice=VOICE,
        config=INSTANT_CONFIG,
    )

    with pytest.raises(BrowserError, match="microphone"):
        asyncio.run(runner.run())

    assert any(e.kind is EventKind.ERROR for e in read_events(paths.events))


def test_a_silent_disconnect_does_not_hang_the_exam(tmp_path: Path) -> None:
    """A browser that vanishes mid-turn must not leave the conductor waiting."""
    transport = FakeTransport(audio_frames(build_pcm([("silence", 200)])))
    paths = SessionPaths.create(tmp_path, session_id="dropped")
    runner = SessionRunner(
        transport=transport,
        driver=ScriptedExamDriver(["Your name?"], "Thank you.", phase=Phase.PART1),
        vad=EnergyVad(),
        tts=SilentTextToSpeech(),
        recorder=SessionRecorder(paths),
        voice=VOICE,
        config=INSTANT_CONFIG,
    )

    with pytest.raises(BrowserError, match="disconnected"):
        asyncio.run(asyncio.wait_for(runner.run(), timeout=5))
