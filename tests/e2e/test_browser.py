"""The exam room in a real browser.

What this proves: the page obtains a microphone, the capture worklet produces
20 ms frames at 16 kHz, those frames cross the WebSocket, the turn detector
endpoints on them, the examiner's audio is played back, and the browser reports
playback so the exam advances. The whole M2 loop, with nothing stubbed but the
voice.

What it cannot prove: **echo cancellation**. Chromium's fake capture device has
no acoustic path, so nothing feeds the loudspeaker signal back into the
microphone. Decision D1 stays unvalidated until someone runs this through real
speakers in a real room, and that is the first thing to check on real hardware.

Silero is not exercised either: the fake device plays noise, which a neural
detector correctly declines to call speech. The energy detector stands in.
"""

import json
import os
import socket
import threading
import time
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from ielts_examiner.audio.frames import SAMPLE_RATE
from ielts_examiner.audio.vad import EnergyVad
from ielts_examiner.config import VoiceProfile
from ielts_examiner.domain.phase import Phase
from ielts_examiner.recording.events import EventKind, read_events
from ielts_examiner.server.app import create_app
from ielts_examiner.server.driver import ScriptedExamDriver
from ielts_examiner.services.fakes import SilentTextToSpeech
from tests.fixtures.synthetic_audio import build_pcm

pytestmark = pytest.mark.browser

QUESTIONS = ["What is your name?", "Where do you live?"]
CLOSING = "Thank you. That is the end of the speaking test."

CHROMIUM_FLAGS = [
    "--use-fake-ui-for-media-stream",  # grant the microphone without a prompt
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
    "--no-sandbox",  # the sandbox cannot be used inside an unprivileged container
]

CHROMIUM_EXECUTABLE = os.environ.get("IELTS_CHROMIUM")
"""Override for environments whose Chromium does not match Playwright's pinned build.

Left unset on a developer machine, where ``playwright install`` provides one.
"""


@pytest.fixture(scope="session")
def capture_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A WAV Chromium plays into the fake microphone, on a loop.

    Speech then silence, so the turn detector sees turns rather than a drone.
    """
    path = tmp_path_factory.mktemp("audio") / "candidate.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(build_pcm([("speech", 1_500), ("silence", 1_500)]))
    return path


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    """Where the server under test writes its session directories."""
    return tmp_path / "sessions"


@pytest.fixture
def server_url(sessions_dir: Path) -> Iterator[str]:
    """Run the application on a free port for the duration of one test."""
    app = create_app(
        driver_factory=lambda: ScriptedExamDriver(QUESTIONS, CLOSING, phase=Phase.PART1),
        vad_factory=EnergyVad,
        tts=SilentTextToSpeech(),
        voice=VoiceProfile(name="test-voice"),
        sessions_dir=sessions_dir,
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_until_listening(port)
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def started_exam(server_url: str, capture_file: Path) -> Iterator["object"]:
    """A page with the exam under way, failing the test on any page error."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=CHROMIUM_EXECUTABLE,
            args=[*CHROMIUM_FLAGS, f"--use-file-for-fake-audio-capture={capture_file}"],
        )
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        page.goto(server_url)
        page.click("#start")
        try:
            yield page
        finally:
            browser.close()
        assert not errors, f"the page raised: {errors}"


def test_the_exam_runs_end_to_end(started_exam, sessions_dir: Path) -> None:  # type: ignore[no-untyped-def]
    started_exam.wait_for_function(
        "() => document.querySelector('#status').textContent.startsWith('finished')",
        timeout=60_000,
    )

    assert started_exam.inner_text("#status") == "finished (completed)"

    events = list(read_events(next(sessions_dir.iterdir()) / "events.jsonl"))
    spoken = [event.data["text"] for event in events if event.kind is EventKind.EXAMINER_UTTERANCE]
    assert spoken == [*QUESTIONS, CLOSING], "the exam advanced through every question"
    assert any(event.kind is EventKind.TURN_DECISION for event in events)


def test_the_candidate_audio_reaches_the_recording(started_exam, sessions_dir: Path) -> None:  # type: ignore[no-untyped-def]
    """Microphone audio must survive the worklet, the socket and the recorder."""
    started_exam.wait_for_function(
        "() => document.querySelector('#status').textContent.startsWith('finished')",
        timeout=60_000,
    )

    recording = next(sessions_dir.iterdir()) / "candidate.wav"
    with wave.open(str(recording), "rb") as handle:
        assert handle.getframerate() == SAMPLE_RATE
        assert handle.getnchannels() == 1
        assert handle.getnframes() > SAMPLE_RATE, "at least a second of audio was captured"


def test_the_capture_contract_holds_in_the_browser(started_exam) -> None:  # type: ignore[no-untyped-def]
    """The server assumes 20 ms frames at 16 kHz; nothing else checks."""
    started_exam.wait_for_function("() => window.__frames !== undefined", timeout=30_000)
    observed = json.loads(started_exam.evaluate("JSON.stringify(window.__frames)"))

    assert observed == {"sampleRate": SAMPLE_RATE, "samplesPerFrame": 320}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_listening(port: int, *, timeout_s: float = 10.0) -> None:
    """Block until the server accepts connections, or give up."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"server did not start on port {port}")
