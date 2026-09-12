"""Deterministic stand-ins for the three services.

These exist so the full test suite and the replay tool run with no credential,
no network and no cost. They are honest about their limits: none of them
pretends to be intelligent, and every one records what it was asked to do so
tests can assert on the interaction rather than on the output.
"""

from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field

from ielts_examiner.audio.frames import SAMPLE_RATE, AudioFrame
from ielts_examiner.config import VoiceProfile
from ielts_examiner.services.protocols import TranscriptUpdate, Word

_BYTES_PER_SAMPLE = 2
_SPEAKING_RATE_CHARS_PER_SECOND = 14.0
"""Rough conversational pace. Only the duration matters, never the content."""


@dataclass
class ScriptedSpeechToText:
    """Emits a fixed sequence of transcript updates as audio flows past.

    The schedule is expressed in frames rather than seconds so that a replay at
    any speed produces identical results.
    """

    updates: Sequence[tuple[int, TranscriptUpdate]]
    """``(frame_index, update)`` pairs, in ascending order of frame index."""

    frames_seen: int = field(default=0, init=False)

    async def stream(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[TranscriptUpdate]:
        """Yield each scheduled update once its frame index has gone by."""
        pending = list(self.updates)
        async for _ in frames:
            self.frames_seen += 1
            while pending and pending[0][0] <= self.frames_seen:
                yield pending.pop(0)[1]
        for _, update in pending:
            yield update


@dataclass
class SilentTextToSpeech:
    """Produces silence of a plausible duration for the text it is given.

    Duration is what the turn-taking machinery actually depends on -- how long
    the examiner holds the floor -- so silence of the right length exercises the
    same code paths a real voice would.
    """

    chunk_ms: int = 100
    requests: list[tuple[str, VoiceProfile]] = field(default_factory=list)

    async def synthesize(self, text: str, voice: VoiceProfile) -> AsyncIterator[bytes]:
        """Yield PCM16 silence lasting as long as ``text`` would take to speak."""
        self.requests.append((text, voice))
        chunk = bytes(SAMPLE_RATE * self.chunk_ms // 1000 * _BYTES_PER_SAMPLE)
        for _ in range(self._chunk_count(text)):
            yield chunk

    def _chunk_count(self, text: str) -> int:
        """Number of chunks covering the estimated duration, at least one."""
        seconds = len(text) / _SPEAKING_RATE_CHARS_PER_SECOND
        return max(1, round(seconds * 1000 / self.chunk_ms))


@dataclass
class CannedLanguageModel:
    """Returns queued responses in order.

    Runs out loudly rather than quietly: an exhausted queue means the test asked
    for a generation it did not anticipate, which is worth failing on.
    """

    responses: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def generate(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        """Pop the next queued response.

        Raises:
            RuntimeError: if no response is queued.
        """
        self.calls.append((system, user))
        if not self.responses:
            raise RuntimeError(f"CannedLanguageModel exhausted after {len(self.calls)} call(s)")
        return self.responses.pop(0)


def transcript(text: str, *, is_final: bool = False, confidence: float = 0.95) -> TranscriptUpdate:
    """Build a transcript update with evenly spaced words.

    A convenience for tests and for the replay tool, where the exact word timings
    do not matter but their presence does.
    """
    return TranscriptUpdate(
        text=text,
        is_final=is_final,
        words=tuple(_evenly_spaced(text.split(), confidence)) if is_final else (),
    )


def _evenly_spaced(tokens: Iterable[str], confidence: float, *, word_ms: int = 300) -> list[Word]:
    """Lay ``tokens`` out back to back, one every ``word_ms``."""
    return [
        Word(
            text=token,
            start_ms=index * word_ms,
            end_ms=(index + 1) * word_ms,
            confidence=confidence,
        )
        for index, token in enumerate(tokens)
    ]
