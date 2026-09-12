"""Re-running a recorded session through the turn-taking pipeline.

The highest-leverage development tool in the project. Calibrating endpointing
against a live microphone means speaking the same sentence fifty times and
trusting your memory of what happened; replaying a recording turns the same work
into a two-second test that can be diffed.

Replay is deliberately *not* real time. It runs as fast as the CPU allows and
derives every timestamp from the audio itself, so a run is reproducible and a
change in behaviour can only come from a change in the policy.
"""

import wave
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from ielts_examiner.audio.frames import FRAME_MS, SAMPLE_RATE, AudioFrame, iter_frames
from ielts_examiner.audio.vad import EnergyVad, VoiceActivityDetector
from ielts_examiner.config import DEFAULT_TURN_CONFIG, TurnConfig
from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision, TurnSignals
from ielts_examiner.turntaking.detector import TurnDetector

_EXPECTED_CHANNELS = 1
_EXPECTED_SAMPLE_WIDTH = 2


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    """A decision the policy reached during replay, with its justification."""

    at_ms: int
    decision: TurnDecision
    signals: TurnSignals


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Outcome of replaying one recording."""

    duration_ms: int
    frame_count: int
    speech_ms: int
    decisions: tuple[ReplayDecision, ...]
    """Transitions only: the frame at which each decision first held.

    The policy is instantaneous by design, so ``ENDPOINT`` stays true for every
    frame of the pause that produced it -- six thousand identical rows in a
    two-minute recording. What a reader wants, and what the runtime acts on, is
    the moment it *became* true. Recording edges rather than levels is the
    replay tool's job, not the policy's: keeping the policy stateless is what
    makes it testable.
    """

    def of_kind(self, decision: TurnDecision) -> tuple[ReplayDecision, ...]:
        """Decisions of one kind, in order. Convenience for assertions."""
        return tuple(item for item in self.decisions if item.decision is decision)


def replay_frames(
    frames: Iterable[AudioFrame],
    *,
    phase: Phase,
    transcript_at: Sequence[tuple[int, str]] = (),
    vad: VoiceActivityDetector | None = None,
    config: TurnConfig = DEFAULT_TURN_CONFIG,
) -> ReplayResult:
    """Drive the turn detector over a sequence of frames.

    Args:
        frames: the audio to replay, in order.
        phase: the exam phase to replay under. The same recording endpoints very
            differently in Part 1 and in the Part 2 long turn, which is the
            behaviour this tool exists to check.
        transcript_at: ``(at_ms, partial_transcript)`` pairs, applied as the
            replay clock passes each one. Stands in for the recogniser.
        vad: voice activity detector. Defaults to a fresh :class:`EnergyVad`.
        config: turn-taking configuration.

    Returns:
        Every non-trivial decision, plus totals for a quick sanity check.
    """
    detector = TurnDetector(config)
    detector.begin_phase(phase, at_ms=0)
    activity = vad or EnergyVad()
    pending = sorted(transcript_at)

    decisions: list[ReplayDecision] = []
    previous = TurnDecision.KEEP_LISTENING
    frame_count = 0
    speech_ms = 0
    last_at_ms = 0

    for frame in frames:
        while pending and pending[0][0] <= frame.at_ms:
            detector.update_transcript(pending.pop(0)[1])

        is_speech = activity.is_speech(frame)
        decision = detector.observe(is_speech=is_speech, energy=frame.rms, at_ms=frame.at_ms)

        frame_count += 1
        speech_ms += FRAME_MS if is_speech else 0
        last_at_ms = frame.at_ms
        if decision is not previous and decision is not TurnDecision.KEEP_LISTENING:
            decisions.append(
                ReplayDecision(
                    at_ms=frame.at_ms,
                    decision=decision,
                    signals=detector.signals(at_ms=frame.at_ms),
                )
            )
        previous = decision

    return ReplayResult(
        duration_ms=last_at_ms + FRAME_MS if frame_count else 0,
        frame_count=frame_count,
        speech_ms=speech_ms,
        decisions=tuple(decisions),
    )


def replay_wav(path: Path, *, phase: Phase, **kwargs: object) -> ReplayResult:
    """Replay a recorded WAV file.

    Args:
        path: a 16 kHz mono PCM16 file, as written by the session recorder.
        phase: the exam phase to replay under.
        **kwargs: forwarded to :func:`replay_frames`.

    Returns:
        The replay result.

    Raises:
        ValueError: if the file is not in the session recording format. Replaying
            resampled or stereo audio would silently change the very thresholds
            being calibrated, so it is refused rather than converted.
    """
    return replay_frames(read_wav_frames(path), phase=phase, **kwargs)  # type: ignore[arg-type]


def read_wav_frames(path: Path) -> Iterator[AudioFrame]:
    """Read a session WAV file as 20 ms frames.

    Raises:
        ValueError: if the file is not 16 kHz mono PCM16.
    """
    with wave.open(str(path), "rb") as handle:
        channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
        if (channels, width, rate) != (_EXPECTED_CHANNELS, _EXPECTED_SAMPLE_WIDTH, SAMPLE_RATE):
            raise ValueError(
                f"{path}: expected {SAMPLE_RATE} Hz mono PCM16, "
                f"got {rate} Hz, {channels} channel(s), {width * 8}-bit"
            )
        pcm = handle.readframes(handle.getnframes())
    yield from iter_frames(pcm)
