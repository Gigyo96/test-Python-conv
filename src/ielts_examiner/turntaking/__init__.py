"""Deciding when the candidate has finished speaking.

The hardest problem in the system, and the one most worth isolating. It is split
in two on purpose:

* ``policy`` is a pure function. All the judgement lives here, and it is tested
  from a table of cases with no audio involved.
* ``detector`` is the stateful shell that turns a stream of audio frames into
  the inputs that function expects. It contains bookkeeping only.
"""

from ielts_examiner.turntaking.detector import TurnDetector
from ielts_examiner.turntaking.policy import decide

__all__ = ["TurnDetector", "decide"]
