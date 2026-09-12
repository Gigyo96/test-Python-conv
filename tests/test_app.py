"""The application over a real WebSocket.

Between this and ``test_session_runner`` the difference is the wire: here the
protocol is actually encoded, framed and parsed, and the static front end is
actually served. The client below is a small Python stand-in for the browser --
which is also the clearest statement of what the browser has to do.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ielts_examiner.audio.vad import EnergyVad
from ielts_examiner.config import VoiceProfile
from ielts_examiner.domain.phase import Phase
from ielts_examiner.recording.events import EventKind, read_events
from ielts_examiner.server.app import create_app
from ielts_examiner.server.driver import ScriptedExamDriver
from ielts_examiner.services.fakes import SilentTextToSpeech
from tests.fixtures.synthetic_audio import build_pcm

QUESTIONS = ["What is your name?", "Where do you live?"]
CLOSING = "Thank you. That is the end of the speaking test."
AN_ANSWER = build_pcm([("speech", 1_200), ("silence", 1_200)])


def build_client(tmp_path: Path) -> TestClient:
    app = create_app(
        driver_factory=lambda: ScriptedExamDriver(QUESTIONS, CLOSING, phase=Phase.PART1),
        vad_factory=EnergyVad,
        tts=SilentTextToSpeech(),
        voice=VoiceProfile(name="test-voice"),
        sessions_dir=tmp_path,
    )
    return TestClient(app)


def conduct(websocket) -> list[dict]:  # type: ignore[no-untyped-def]
    """Play the browser's part: acknowledge playback, then answer.

    Returns every control event the server sent.
    """
    websocket.send_text(json.dumps({"type": "hello", "sample_rate": 16000}))
    events: list[dict] = []
    while True:
        message = websocket.receive()
        if message.get("bytes") is not None:
            continue  # examiner audio; a browser would play it
        event = json.loads(message["text"])
        events.append(event)
        if event["type"] == "utterance_end":
            websocket.send_text(
                json.dumps({"type": "playback_finished", "utterance_id": event["utterance_id"]})
            )
            _answer(websocket)
        elif event["type"] == "session_end":
            return events


def _answer(websocket) -> None:  # type: ignore[no-untyped-def]
    """Send one spoken answer followed by a pause, 20 ms at a time."""
    for offset in range(0, len(AN_ANSWER), 640):
        websocket.send_bytes(AN_ANSWER[offset : offset + 640])


def test_a_whole_exam_runs_over_the_websocket(tmp_path: Path) -> None:
    with build_client(tmp_path).websocket_connect("/ws") as websocket:
        events = conduct(websocket)

    spoken = [event["text"] for event in events if event["type"] == "utterance_begin"]
    assert spoken == [*QUESTIONS, CLOSING]
    assert events[0]["type"] == "ready"
    assert events[-1] == {"type": "session_end", "reason": "completed"}


def test_the_session_lands_on_disk(tmp_path: Path) -> None:
    with build_client(tmp_path).websocket_connect("/ws") as websocket:
        conduct(websocket)

    sessions = list(tmp_path.iterdir())
    assert len(sessions) == 1
    kinds = {event.kind for event in read_events(sessions[0] / "events.jsonl")}
    assert EventKind.TURN_DECISION in kinds
    assert (sessions[0] / "candidate.wav").stat().st_size > 0


def test_the_exam_room_is_served(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    assert "IELTS Speaking" in client.get("/").text
    for asset in ("app.js", "capture-worklet.js", "style.css"):
        assert client.get(f"/{asset}").status_code == 200


def test_the_page_requests_echo_cancellation_without_the_other_processing() -> None:
    """Decision D2, asserted where it actually takes effect.

    Noise suppression or gain control silently switched on would degrade the
    pronunciation assessment months later, with nothing to point at.
    """
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text()

    assert "echoCancellation: true" in source
    assert "noiseSuppression: false" in source
    assert "autoGainControl: false" in source
