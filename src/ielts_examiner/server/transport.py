"""The connection to the browser, behind a protocol.

The session runner sends events and audio and consumes incoming messages; it
never touches a socket. That seam is what lets the whole exam loop be tested in
memory, and what would let the browser be replaced by a native client without
the runner noticing.
"""

from collections.abc import AsyncIterator
from typing import Protocol

from fastapi import WebSocket

from ielts_examiner.server.protocol import AudioChunk, ClientMessage, ServerEvent, encode, parse


class ClientTransport(Protocol):
    """A bidirectional channel carrying control events and audio."""

    async def send(self, event: ServerEvent) -> None:
        """Deliver a control event."""
        ...

    async def send_audio(self, pcm: bytes) -> None:
        """Deliver examiner audio."""
        ...

    def incoming(self) -> AsyncIterator[ClientMessage]:
        """Yield messages until the client disconnects."""
        ...


class WebSocketTransport:
    """A :class:`ClientTransport` over one FastAPI WebSocket."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket

    async def send(self, event: ServerEvent) -> None:
        """Send a control event as a JSON text frame."""
        await self._websocket.send_text(encode(event))

    async def send_audio(self, pcm: bytes) -> None:
        """Send examiner audio as a binary frame."""
        await self._websocket.send_bytes(pcm)

    async def incoming(self) -> AsyncIterator[ClientMessage]:
        """Yield client messages until the socket closes.

        Binary frames are audio and text frames are control, so the two never
        have to be told apart by inspecting their content.
        """
        while True:
            message = await self._websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if (pcm := message.get("bytes")) is not None:
                yield AudioChunk(pcm=pcm)
            elif (text := message.get("text")) is not None:
                yield parse(text)
