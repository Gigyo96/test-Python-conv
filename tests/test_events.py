"""The event log and the session directory layout."""

from pathlib import Path

import pytest

from ielts_examiner.recording.events import Event, EventKind, EventLog, read_events
from ielts_examiner.recording.session import SessionPaths


def test_events_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(EventKind.SESSION_START, at_ms=0, seed=42)
        log.append(EventKind.PHASE_ENTER, at_ms=1_200, phase="part1")
        log.append(EventKind.TURN_DECISION, at_ms=4_900, decision="endpoint", silence_ms=740)

    events = list(read_events(path))
    assert [event.kind for event in events] == [
        EventKind.SESSION_START,
        EventKind.PHASE_ENTER,
        EventKind.TURN_DECISION,
    ]
    assert events[2].data == {"decision": "endpoint", "silence_ms": 740}


def test_each_append_is_durable(tmp_path: Path) -> None:
    """A session killed mid-exam must still yield everything up to the failure."""
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(EventKind.PHASE_ENTER, at_ms=0, phase="intro")

    assert len(list(read_events(path))) == 1  # read before close


def test_appending_to_an_existing_log_does_not_truncate_it(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(EventKind.SESSION_START, at_ms=0)
    with EventLog(path) as log:
        log.append(EventKind.SESSION_END, at_ms=10)

    assert len(list(read_events(path))) == 2


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(Event(EventKind.SESSION_START, 0).to_json() + "\n\n", encoding="utf-8")

    assert len(list(read_events(path))) == 1


def test_a_corrupt_line_is_surfaced_not_swallowed(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed event line"):
        list(read_events(path))


def test_an_unknown_event_kind_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"kind": "telepathy", "at_ms": 0, "data": {}}\n', encoding="utf-8")

    with pytest.raises(ValueError):
        list(read_events(path))


def test_session_paths_are_all_inside_one_directory(tmp_path: Path) -> None:
    paths = SessionPaths.create(tmp_path, session_id="exam-1")

    files = [paths.events, paths.metrics, paths.candidate_audio, paths.transcript, paths.report]
    assert all(path.parent == paths.root for path in files)
    assert paths.root.is_dir()


def test_manifest_records_what_produced_the_session(tmp_path: Path) -> None:
    paths = SessionPaths.create(tmp_path, session_id="exam-1")
    paths.write_manifest(seed=7, bank_version="2026.09", voice="en-GB-example")

    assert '"seed": 7' in paths.manifest.read_text(encoding="utf-8")
