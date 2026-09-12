"""The phases of an IELTS Speaking exam."""

from enum import StrEnum


class Phase(StrEnum):
    """A stage of the exam, in the order the examiner walks through it.

    The phase is the single most important piece of context in the system: it
    decides how long a pause is allowed to last, whether the microphone is even
    listened to, and which script the examiner reads from.
    """

    INTRO = "intro"
    """Greeting and identity check."""

    PART1 = "part1"
    """Short questions on familiar topics (4-5 minutes)."""

    PART2_PREP = "part2_prep"
    """One silent minute to read the cue card and take notes."""

    PART2_LONG_TURN = "part2_long_turn"
    """The candidate speaks alone for one to two minutes."""

    PART2_ROUNDING = "part2_rounding"
    """One or two short follow-up questions closing Part 2."""

    PART3 = "part3"
    """Abstract discussion linked to the Part 2 topic (4-5 minutes)."""

    CLOSING = "closing"
    """The examiner's closing formula. Nothing is expected from the candidate."""

    @property
    def listens_to_candidate(self) -> bool:
        """Whether candidate speech can end this phase.

        During preparation the candidate may well mutter while taking notes, and
        during the closing formula the exam is already over. In both cases the
        phase ends on a timer, so anything the microphone picks up is ignored.
        """
        return self not in _NON_LISTENING_PHASES


_NON_LISTENING_PHASES = frozenset({Phase.PART2_PREP, Phase.CLOSING})
