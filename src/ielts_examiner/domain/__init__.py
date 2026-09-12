"""Pure domain types: no I/O, no framework, no side effects.

Every module in this package must be importable and fully exercisable without a
microphone, a network connection or a credential. That constraint is what makes
the turn-taking policy testable with a plain table of cases.
"""

from ielts_examiner.domain.phase import Phase
from ielts_examiner.domain.turn import TurnDecision, TurnSignals

__all__ = ["Phase", "TurnDecision", "TurnSignals"]
