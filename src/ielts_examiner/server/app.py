"""The local web application.

Serves the exam room and accepts one WebSocket per session. Deliberately thin:
it wires collaborators together and owns nothing. What a session *does* is
:class:`~ielts_examiner.server.session_runner.SessionRunner`.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from ielts_examiner.audio.vad import VoiceActivityDetector
from ielts_examiner.config import SESSIONS_DIR, VoiceProfile
from ielts_examiner.recording.recorder import SessionRecorder
from ielts_examiner.recording.session import SessionPaths
from ielts_examiner.server.driver import ExamDriver
from ielts_examiner.server.session_runner import BrowserError, SessionRunner
from ielts_examiner.server.transport import WebSocketTransport
from ielts_examiner.services.protocols import TextToSpeech

WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
"""The static front end. Kept outside the package: it is not Python."""

_log = logging.getLogger(__name__)


def create_app(
    *,
    driver_factory: Callable[[], ExamDriver],
    vad_factory: Callable[[], VoiceActivityDetector],
    tts: TextToSpeech,
    voice: VoiceProfile,
    sessions_dir: Path = SESSIONS_DIR,
    web_root: Path = WEB_ROOT,
) -> FastAPI:
    """Build the application.

    Collaborators arrive as factories rather than instances because each session
    needs its own: a voice activity detector and a driver both carry state that
    must not leak from one exam into the next.
    """
    app = FastAPI(title="IELTS Speaking examiner")

    @app.websocket("/ws")
    async def session(websocket: WebSocket) -> None:
        await websocket.accept()
        paths = SessionPaths.create(sessions_dir)
        paths.write_manifest(voice=voice.name, language=voice.language_code)
        _log.info("session started: %s", paths.root)
        runner = SessionRunner(
            transport=WebSocketTransport(websocket),
            driver=driver_factory(),
            vad=vad_factory(),
            tts=tts,
            recorder=SessionRecorder(paths),
            voice=voice,
        )
        try:
            await runner.run()
        except BrowserError as failure:
            _log.warning("session ended early: %s", failure)

    app.mount("/", StaticFiles(directory=web_root, html=True), name="web")
    return app
