"""Conducting one exam session.

The orchestrator. It owns the audio clock, the turn detector and the transport,
and it delegates every judgement: what to say next is the driver's, when the
candidate has finished is the policy's, whether a frame is speech is the
detector's.

Two coroutines run concurrently. A reader consumes the client stream without
ever blocking -- microphone audio keeps flowing even while the examiner speaks,
because that is the only way to notice an interruption. A conductor walks the
exam, alternating between speaking and waiting for a turn to end. They meet at
one queue and one event.
"""

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import TypeVar

from ielts_examiner.audio.frames import FRAME_MS, SAMPLE_RATE, iter_frames
from ielts_examiner.audio.vad import VoiceActivityDetector
from ielts_examiner.config import DEFAULT_TURN_CONFIG, TurnConfig, VoiceProfile
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision
from ielts_examiner.recording.events import EventKind
from ielts_examiner.recording.recorder import SessionRecorder
from ielts_examiner.server.driver import (
    Announce,
    Ask,
    ExamAction,
    ExamDriver,
    Finish,
    TurnOutcome,
)
from ielts_examiner.server.protocol import (
    AudioChunk,
    ClientError,
    Hello,
    PhaseChanged,
    PlaybackFinished,
    Ready,
    SessionEnd,
    StopPlayback,
    UtteranceBegin,
    UtteranceEnd,
)
from ielts_examiner.server.transport import ClientTransport
from ielts_examiner.services.protocols import TextToSpeech
from ielts_examiner.turntaking.detector import TurnDetector

T = TypeVar("T")

_PLAYBACK_GRACE_MS = 2_000
"""Slack added to the estimated playback time before giving up on the browser.

A lost acknowledgement must not wedge the exam forever, but cutting an utterance
short would be worse, so the fallback is generous.
"""

_BYTES_PER_SAMPLE = 2


class BrowserError(RuntimeError):
    """The browser reported that it cannot continue, typically no microphone."""


class SessionRunner:
    """Runs one exam from the greeting to the closing formula."""

    def __init__(
        self,
        *,
        transport: ClientTransport,
        driver: ExamDriver,
        vad: VoiceActivityDetector,
        tts: TextToSpeech,
        recorder: SessionRecorder,
        voice: VoiceProfile,
        config: TurnConfig = DEFAULT_TURN_CONFIG,
    ) -> None:
        self._transport = transport
        self._driver = driver
        self._vad = vad
        self._tts = tts
        self._recorder = recorder
        self._voice = voice
        self._config = config

        self._detector = TurnDetector(config)
        self._clock_ms = 0
        self._utterances = 0
        self._listening = False
        self._last_decision = TurnDecision.KEEP_LISTENING
        self._turn_ended: asyncio.Queue[TurnDecision] = asyncio.Queue()
        self._playback_done = asyncio.Event()
        self._announced_phase: Phase | None = None

    async def run(self) -> None:
        """Conduct the session, then close the recording.

        Raises:
            BrowserError: if the browser reported it cannot continue.
        """
        self._recorder.event(EventKind.SESSION_START, at_ms=0, sample_rate=SAMPLE_RATE)
        await self._transport.send(Ready())
        reader = asyncio.create_task(self._read_client())
        try:
            reason = await self._conduct(reader)
            await self._transport.send(SessionEnd(reason=reason))
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            self._recorder.event(EventKind.SESSION_END, at_ms=self._clock_ms)
            self._recorder.close()

    async def _conduct(self, reader: asyncio.Task[None]) -> str:
        """Walk the exam, alternating between speaking and listening.

        The reader task is awaited alongside every wait so that a disconnect or a
        client failure surfaces immediately instead of hanging the exam.
        """
        outcome: TurnOutcome | None = None
        while True:
            await self._announce_phase()
            action: ExamAction = self._driver.next_action(outcome)
            outcome = None
            match action:
                case Finish(reason=reason):
                    return reason
                case Announce(text=text):
                    await self._speak(text, reader)
                case Ask(text=text):
                    await self._speak(text, reader)
                    outcome = await self._listen(reader)

    async def _announce_phase(self) -> None:
        """Tell the browser about a phase change, once per change."""
        phase = self._driver.phase
        if phase is self._announced_phase:
            return
        self._announced_phase = phase
        self._detector.begin_phase(phase, at_ms=self._clock_ms)
        self._recorder.event(EventKind.PHASE_ENTER, at_ms=self._clock_ms, phase=str(phase))
        await self._transport.send(PhaseChanged(phase=phase))

    async def _speak(self, text: str, reader: asyncio.Task[None]) -> None:
        """Pause, synthesise, stream to the browser and wait for it to finish."""
        await self._pause_before_speaking(reader)

        self._utterances += 1
        utterance_id = self._utterances
        self._detector.set_examiner_speaking(True)
        self._playback_done.clear()
        self._recorder.event(
            EventKind.EXAMINER_UTTERANCE, at_ms=self._clock_ms, id=utterance_id, text=text
        )

        await self._transport.send(UtteranceBegin(utterance_id=utterance_id, text=text))
        spoken_bytes = 0
        async for chunk in self._tts.synthesize(text, self._voice):
            self._recorder.examiner_audio(chunk)
            await self._transport.send_audio(chunk)
            spoken_bytes += len(chunk)
        await self._transport.send(UtteranceEnd(utterance_id=utterance_id))

        await self._await_playback(spoken_bytes, reader)
        self._detector.set_examiner_speaking(False)

    async def _pause_before_speaking(self, reader: asyncio.Task[None]) -> None:
        """Take the beat a human examiner takes to write on the form (section 5)."""
        delay_ms = self._config.tuning_for(self._driver.phase).response_delay_ms
        if delay_ms:
            await self._race(asyncio.sleep(delay_ms / 1000), reader)

    async def _await_playback(self, spoken_bytes: int, reader: asyncio.Task[None]) -> None:
        """Wait for the browser to report the utterance played out.

        Falls back to the estimated duration plus a grace period: a lost
        acknowledgement must not wedge the exam.
        """
        estimated_ms = spoken_bytes * 1000 // (SAMPLE_RATE * _BYTES_PER_SAMPLE)
        timeout = (estimated_ms + _PLAYBACK_GRACE_MS) / 1000
        with contextlib.suppress(TimeoutError):
            await self._race(asyncio.wait_for(self._playback_done.wait(), timeout), reader)

    async def _listen(self, reader: asyncio.Task[None]) -> TurnOutcome:
        """Wait for the candidate's turn to end and report how it ended."""
        self._detector.start_new_turn()
        self._last_decision = TurnDecision.KEEP_LISTENING
        self._listening = True
        try:
            decision = await self._race(self._turn_ended.get(), reader)
        finally:
            self._listening = False
        signals = self._detector.signals(at_ms=self._clock_ms)
        return TurnOutcome(
            phase=self._driver.phase,
            decision=decision,
            transcript=signals.partial_transcript,
            speech_ms=signals.speech_ms,
        )

    async def _read_client(self) -> None:
        """Consume the client stream until it ends.

        Raises:
            BrowserError: when the browser reports it cannot continue.
        """
        async for message in self._transport.incoming():
            match message:
                case AudioChunk(pcm=pcm):
                    await self._on_audio(pcm)
                case PlaybackFinished():
                    self._playback_done.set()
                case Hello(sample_rate=rate):
                    self._recorder.event(EventKind.SESSION_START, at_ms=0, client_rate=rate)
                case ClientError(message=text):
                    self._recorder.event(EventKind.ERROR, at_ms=self._clock_ms, message=text)
                    raise BrowserError(text)

    async def _on_audio(self, pcm: bytes) -> None:
        """Record microphone audio and advance the turn detector over it."""
        self._recorder.candidate_audio(pcm)
        for frame in iter_frames(pcm, start_ms=self._clock_ms):
            decision = self._detector.observe(
                is_speech=self._vad.is_speech(frame), energy=frame.rms, at_ms=frame.at_ms
            )
            self._clock_ms = frame.at_ms + FRAME_MS
            await self._on_decision(decision)

    async def _on_decision(self, decision: TurnDecision) -> None:
        """React to a decision, but only when it first becomes true.

        The policy is instantaneous by design, so a decision holds for every
        frame of the pause that produced it. Acting on the level rather than the
        edge would interrupt the candidate once per frame.
        """
        if decision is self._last_decision:
            return
        self._last_decision = decision
        if decision is TurnDecision.KEEP_LISTENING:
            return

        self._recorder.event(
            EventKind.TURN_DECISION,
            at_ms=self._clock_ms,
            decision=str(decision),
            **self._signal_summary(),
        )
        if decision is TurnDecision.BARGE_IN:
            await self._transport.send(StopPlayback())
            self._playback_done.set()
        elif self._listening:
            await self._turn_ended.put(decision)

    def _signal_summary(self) -> dict[str, int | str]:
        """The signals behind a decision, for after-the-fact calibration."""
        signals = self._detector.signals(at_ms=self._clock_ms)
        return {
            "silence_ms": signals.silence_ms,
            "speech_ms": signals.speech_ms,
            "phase_elapsed_ms": signals.phase_elapsed_ms,
            "transcript": signals.partial_transcript,
        }

    @staticmethod
    async def _race(awaitable: Awaitable[T], reader: asyncio.Task[None]) -> T:
        """Await something, but surface a reader failure or disconnect first.

        Without this a client that vanishes mid-turn would leave the conductor
        waiting on a queue nobody will ever fill.
        """
        work = asyncio.ensure_future(awaitable)
        done, _ = await asyncio.wait({work, reader}, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return work.result()
        work.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await work
        reader.result()  # re-raises BrowserError, or returns on a clean disconnect
        raise BrowserError("the browser disconnected before the exam finished")
