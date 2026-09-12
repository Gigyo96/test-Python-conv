"""An in-memory client, for testing the session runner without a socket.

Everything the runner sends is captured; everything the fake client should say
is scripted in advance. Audio is delivered frame by frame so a test can describe
a candidate's turn as "two seconds of speech, then a pause".
"""

import asyncio
from collections.abc import AsyncIterator, Iterable

from ielts_examiner.audio.frames import SAMPLES_PER_FRAME, iter_frames
from ielts_examiner.server.protocol import (
    ClientMessage,
    PlaybackFinished,
    ServerEvent,
    UtteranceEnd,
)


class FakeTransport:
    """Replays a scripted client and records what the server sent it.

    Acknowledges playback automatically, as a real browser does: without that the
    runner would wait out its timeout after every utterance.
    """

    def __init__(
        self, script: Iterable[ClientMessage], *, acknowledge_playback: bool = True
    ) -> None:
        self._script = list(script)
        self._acknowledge_playback = acknowledge_playback
        self._injected: asyncio.Queue[ClientMessage] = asyncio.Queue()
        self.events: list[ServerEvent] = []
        self.audio: list[bytes] = []

    async def send(self, event: ServerEvent) -> None:
        """Capture a control event, acknowledging playback like a browser would."""
        self.events.append(event)
        if self._acknowledge_playback and isinstance(event, UtteranceEnd):
            await self._injected.put(PlaybackFinished(utterance_id=event.utterance_id))

    async def send_audio(self, pcm: bytes) -> None:
        """Capture examiner audio."""
        self.audio.append(pcm)

    async def incoming(self) -> AsyncIterator[ClientMessage]:
        """Yield injected messages first, then the script, then stop.

        Yielding control between messages lets the runner's conductor make
        progress, which is what a real socket would do anyway.
        """
        for message in self._script:
            while not self._injected.empty():
                yield self._injected.get_nowait()
            yield message
            await asyncio.sleep(0)
        while not self._injected.empty():
            yield self._injected.get_nowait()

    def spoken_text(self) -> list[str]:
        """Every utterance the examiner began, in order."""
        from ielts_examiner.server.protocol import UtteranceBegin

        return [event.text for event in self.events if isinstance(event, UtteranceBegin)]


def audio_frames(pcm: bytes) -> list[ClientMessage]:
    """Split PCM into one client message per 20 ms frame."""
    from ielts_examiner.server.protocol import AudioChunk

    return [
        AudioChunk(pcm=frame.samples.tobytes())
        for frame in iter_frames(pcm)
        if frame.samples.size == SAMPLES_PER_FRAME
    ]
