"""Start the examiner and open the exam room.

    python -m ielts_examiner

Until the Director and the Google services land (M4 and M3), this runs the
placeholder driver and a silent voice: enough to prove the audio loop -- capture
with echo cancellation, turn detection, playback, recording -- end to end.
"""

import argparse
import logging
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

import uvicorn

from ielts_examiner.audio.silero import SileroVad
from ielts_examiner.config import SESSIONS_DIR, SILERO_MODEL_PATH, VoiceProfile
from ielts_examiner.domain.phase import Phase
from ielts_examiner.server.app import create_app
from ielts_examiner.server.driver import ScriptedExamDriver
from ielts_examiner.services.fakes import SilentTextToSpeech

PLACEHOLDER_QUESTIONS = [
    "Good morning. Can you tell me your full name, please?",
    "And what can I call you?",
    "Now, let's talk about where you live. What kind of place do you live in?",
]
PLACEHOLDER_CLOSING = "Thank you. That is the end of the speaking test."


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        vad_factory = _silero_factory(args.vad_model)
    except FileNotFoundError as missing:
        print(missing)
        return 1

    app = create_app(
        driver_factory=lambda: ScriptedExamDriver(
            PLACEHOLDER_QUESTIONS, PLACEHOLDER_CLOSING, phase=Phase.PART1
        ),
        vad_factory=vad_factory,
        tts=SilentTextToSpeech(),
        voice=VoiceProfile(name="placeholder"),
        sessions_dir=args.sessions,
    )

    url = f"http://{args.host}:{args.port}/"
    if args.open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"exam room: {url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _silero_factory(model_path: Path) -> Callable[[], SileroVad]:
    """Build the detector factory, failing fast if the model is missing.

    Sharing one detector across sessions would be wrong -- it carries the
    model's recurrent state -- so each session builds its own. Loading once here
    means a missing model is reported at start-up rather than mid-exam.

    Raises:
        FileNotFoundError: if the model is absent.
    """
    SileroVad.load(model_path)
    return lambda: SileroVad.load(model_path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sessions", type=Path, default=SESSIONS_DIR)
    parser.add_argument("--vad-model", type=Path, default=SILERO_MODEL_PATH)
    parser.add_argument(
        "--no-browser", dest="open_browser", action="store_false", help="do not open a tab"
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
