"""The stand-in services that keep the suite credential-free.

The fakes are exercised with ``asyncio.run`` rather than an async test plugin:
one less development dependency, and these coroutines are short enough that the
ceremony is not worth it.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from ielts_examiner.audio.frames import SAMPLES_PER_FRAME, AudioFrame, iter_frames
from ielts_examiner.config import VoiceProfile
from ielts_examiner.services.fakes import (
    CannedLanguageModel,
    ScriptedSpeechToText,
    SilentTextToSpeech,
    transcript,
)

VOICE = VoiceProfile(name="test-voice")
CUE_CARD_SCRIPT = "Now, I'm going to give you a topic and I'd like you to talk about it."


async def frames_from(pcm: bytes) -> AsyncIterator[AudioFrame]:
    """Adapt raw PCM to the async stream the recogniser protocol expects."""
    for frame in iter_frames(pcm):
        yield frame


def test_scripted_stt_emits_updates_on_schedule() -> None:
    stt = ScriptedSpeechToText(
        updates=[(2, transcript("I live")), (5, transcript("I live in Rome", is_final=True))]
    )
    six_frames = bytes(SAMPLES_PER_FRAME * 2 * 6)

    async def run() -> list[str]:
        return [update.text async for update in stt.stream(frames_from(six_frames))]

    assert asyncio.run(run()) == ["I live", "I live in Rome"]


def test_scripted_stt_still_emits_updates_scheduled_past_the_audio() -> None:
    """A recording shorter than the script must not silently drop the remainder."""
    stt = ScriptedSpeechToText(updates=[(99, transcript("late", is_final=True))])

    async def run() -> list[str]:
        return [
            update.text async for update in stt.stream(frames_from(bytes(SAMPLES_PER_FRAME * 2)))
        ]

    assert asyncio.run(run()) == ["late"]


def test_silent_tts_duration_scales_with_the_text() -> None:
    tts = SilentTextToSpeech()

    async def chunk_count(text: str) -> int:
        return len([chunk async for chunk in tts.synthesize(text, VOICE)])

    short = asyncio.run(chunk_count("Thank you."))
    long = asyncio.run(chunk_count(CUE_CARD_SCRIPT))

    assert long > short
    assert [text for text, _ in tts.requests] == ["Thank you.", CUE_CARD_SCRIPT]


def test_canned_model_returns_responses_in_order_then_fails_loudly() -> None:
    model = CannedLanguageModel(responses=["first", "second"])

    async def run() -> None:
        assert await model.generate("system", "a") == "first"
        assert await model.generate("system", "b") == "second"
        with pytest.raises(RuntimeError, match="exhausted"):
            await model.generate("system", "c")

    asyncio.run(run())
    assert len(model.calls) == 3


def test_final_transcripts_carry_word_timings() -> None:
    update = transcript("I live in Rome", is_final=True)

    assert [word.text for word in update.words] == ["I", "live", "in", "Rome"]
    assert update.words[0].end_ms == update.words[1].start_ms


def test_interim_transcripts_carry_no_words() -> None:
    assert transcript("I live in").words == ()
