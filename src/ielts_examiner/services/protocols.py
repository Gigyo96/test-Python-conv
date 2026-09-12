"""The three service interfaces the exam runtime depends on."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from ielts_examiner.audio.frames import AudioFrame
from ielts_examiner.config import VoiceProfile


@dataclass(frozen=True, slots=True)
class Word:
    """One recognised word, located in time and scored for reliability."""

    text: str
    start_ms: int
    end_ms: int
    confidence: float
    """Recogniser confidence in ``[0.0, 1.0]``.

    Load-bearing, not decorative: the assessor excludes low-confidence words from
    error counts so that a candidate is never penalised for grammar the
    recogniser invented on their accent.
    """


@dataclass(frozen=True, slots=True)
class TranscriptUpdate:
    """An interim or final recognition result for the current turn."""

    text: str
    is_final: bool
    words: tuple[Word, ...] = ()
    """Populated on final results. Interim results carry text only."""


class SpeechToText(Protocol):
    """Streaming speech recognition."""

    def stream(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[TranscriptUpdate]:
        """Recognise a stream of audio, emitting interim results as they arrive.

        Interim results are what makes semantic endpointing possible: the policy
        needs to read the tail of the sentence *before* deciding the turn is
        over, which a batch recogniser could never provide in time.
        """
        ...


class TextToSpeech(Protocol):
    """Streaming speech synthesis."""

    def synthesize(self, text: str, voice: VoiceProfile) -> AsyncIterator[bytes]:
        """Synthesise ``text``, yielding PCM16 chunks as they are produced.

        Streaming rather than a single buffer so playback can start on the first
        chunk instead of waiting for the whole utterance.
        """
        ...


class LanguageModel(Protocol):
    """Text generation."""

    async def generate(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        """Produce a completion.

        Args:
            system: the role instruction, such as the examiner's constraints.
            user: the request.
            temperature: low by default; both the examiner and the assessors want
                consistency far more than they want variety.
        """
        ...
