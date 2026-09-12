#!/usr/bin/env python3
"""Replay a recorded session through the turn-taking pipeline.

    python tools/replay.py sessions/2026-09-12T14-33-02Z --phase part2_long_turn

Prints every decision the policy reached and the silence that justified it, so a
mistimed endpoint can be read rather than guessed at.
"""

import argparse
import sys
from pathlib import Path

from ielts_examiner.domain.phase import Phase
from ielts_examiner.recording.session import SessionPaths
from ielts_examiner.replay import ReplayResult, replay_wav


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = _parse_args(argv)
    audio = _resolve_audio(args.target)
    if audio is None:
        print(f"no candidate audio found at {args.target}", file=sys.stderr)
        return 1

    result = replay_wav(audio, phase=Phase(args.phase))
    _print_summary(audio, Phase(args.phase), result)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("target", type=Path, help="session directory or a 16 kHz mono WAV file")
    parser.add_argument(
        "--phase",
        default=Phase.PART1.value,
        choices=[phase.value for phase in Phase],
        help="exam phase to replay under (default: %(default)s)",
    )
    return parser.parse_args(argv)


def _resolve_audio(target: Path) -> Path | None:
    """Accept either a session directory or the WAV file directly."""
    if target.is_file():
        return target
    candidate = SessionPaths(root=target).candidate_audio
    return candidate if candidate.is_file() else None


def _print_summary(audio: Path, phase: Phase, result: ReplayResult) -> None:
    speech_share = result.speech_ms / result.duration_ms if result.duration_ms else 0.0
    print(f"{audio}  phase={phase.value}")
    print(
        f"  {result.duration_ms / 1000:.1f}s, {result.frame_count} frames, "
        f"{speech_share:.0%} speech"
    )
    if not result.decisions:
        print("  no decisions: the candidate never yielded the floor")
        return
    for item in result.decisions:
        print(
            f"  {item.at_ms / 1000:8.2f}s  {item.decision.value:<16}"
            f"silence={item.signals.silence_ms:>5}ms  speech={item.signals.speech_ms:>6}ms"
        )


if __name__ == "__main__":
    raise SystemExit(main())
