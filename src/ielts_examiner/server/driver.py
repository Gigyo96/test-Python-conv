"""What the examiner does next.

The session runner owns audio, timing and transport; it does not know what an
IELTS exam looks like. That knowledge sits behind :class:`ExamDriver`, which the
Director graph will implement in M4.

Keeping the seam here means the runner can be built and tested now against a
driver that reads three lines from a list, and gains a real exam later without
changing a line.
"""

from dataclasses import dataclass
from typing import Protocol

from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision


@dataclass(frozen=True, slots=True)
class Ask:
    """Speak, then wait for the candidate to answer."""

    text: str


@dataclass(frozen=True, slots=True)
class Announce:
    """Speak without expecting an answer, such as the closing formula."""

    text: str


@dataclass(frozen=True, slots=True)
class Finish:
    """The exam is over."""

    reason: str = "completed"


ExamAction = Ask | Announce | Finish


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """What the candidate did during one turn."""

    phase: Phase
    decision: TurnDecision
    """How the turn ended: a natural endpoint, a hard cut-off, or a stall."""

    transcript: str
    speech_ms: int


class ExamDriver(Protocol):
    """Decides the examiner's next move."""

    @property
    def phase(self) -> Phase:
        """The phase currently in progress. Sets the turn-taking thresholds."""
        ...

    def next_action(self, outcome: TurnOutcome | None) -> ExamAction:
        """Choose the next action.

        Args:
            outcome: the turn that just ended, or ``None`` at the start of the
                exam and after an announcement -- neither of which produces a
                candidate turn.
        """
        ...


class ScriptedExamDriver:
    """Reads a fixed list of lines. A placeholder, replaced by the Director in M4.

    Deliberately the dullest thing that exercises the whole loop: speak, listen,
    speak again, close. It has no idea what an exam is, which is the point --
    everything it does is the runner's behaviour, not the driver's.
    """

    def __init__(self, questions: list[str], closing: str, *, phase: Phase = Phase.PART1) -> None:
        self._questions = list(questions)
        self._closing = closing
        self._phase = phase
        self._asked = 0
        self._closed = False
        self.outcomes: list[TurnOutcome] = []
        """Every turn observed, in order. Lets tests assert on what happened."""

    @property
    def phase(self) -> Phase:
        """The single phase this driver operates in."""
        return self._phase

    def next_action(self, outcome: TurnOutcome | None) -> ExamAction:
        """Ask the next question, then close, then finish."""
        if outcome is not None:
            self.outcomes.append(outcome)
        if self._asked < len(self._questions):
            self._asked += 1
            return Ask(self._questions[self._asked - 1])
        if not self._closed:
            self._closed = True
            return Announce(self._closing)
        return Finish()
