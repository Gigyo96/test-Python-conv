"""Layout of a session directory.

One self-contained folder per exam, named after the moment it started. Nothing
in it refers to anything outside it, so a session can be copied to another
machine and assessed, replayed or archived there.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DIRECTORY_TIMESTAMP = "%Y-%m-%dT%H-%M-%SZ"
"""Colons are illegal in Windows paths, so the ISO separator is replaced."""


@dataclass(frozen=True, slots=True)
class SessionPaths:
    """Every file belonging to one exam session."""

    root: Path

    @classmethod
    def create(cls, base: Path, *, session_id: str | None = None) -> "SessionPaths":
        """Create the directory for a new session.

        Args:
            base: directory holding all sessions.
            session_id: folder name. Defaults to the current UTC timestamp.

        Returns:
            Paths rooted at the freshly created directory.
        """
        name = session_id or datetime.now(UTC).strftime(_DIRECTORY_TIMESTAMP)
        root = base / name
        root.mkdir(parents=True, exist_ok=True)
        return cls(root=root)

    @property
    def manifest(self) -> Path:
        """Configuration, seed and content versions that produced this session."""
        return self.root / "manifest.json"

    @property
    def events(self) -> Path:
        """The event log: the source of truth."""
        return self.root / "events.jsonl"

    @property
    def metrics(self) -> Path:
        """Per-turn latency measurements."""
        return self.root / "metrics.jsonl"

    @property
    def candidate_audio(self) -> Path:
        """Continuous 16 kHz mono recording of the microphone."""
        return self.root / "candidate.wav"

    @property
    def examiner_audio(self) -> Path:
        """Continuous recording of what the examiner said."""
        return self.root / "examiner.wav"

    @property
    def transcript(self) -> Path:
        """Words with timestamps and confidence, for the assessor."""
        return self.root / "transcript.json"

    @property
    def report(self) -> Path:
        """The rendered assessment."""
        return self.root / "report.html"

    def write_manifest(self, **entries: Any) -> None:
        """Write the manifest.

        Recording the seed and the content versions here is what makes two
        sessions comparable: without them a band score from last month cannot be
        read against one from today.
        """
        self.manifest.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
