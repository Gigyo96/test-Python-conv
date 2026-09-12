"""A stand-in for the Silero model.

The ONNX model can only be judged against real speech, which no synthetic
fixture provides. What *can* be tested is everything around it: that frames are
buffered into windows of the right size, that each window is scored once, and
that the gate debounces the result. This stub makes that possible.
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class StubProbabilityModel:
    """Returns queued probabilities, one per window, holding the last one."""

    probabilities: list[float] = field(default_factory=list)
    windows: list[int] = field(default_factory=list)
    """Size of every window it was asked to score, for asserting on buffering."""

    def probability(self, window: np.ndarray) -> float:
        """Score a window, consuming the next queued probability."""
        self.windows.append(int(window.size))
        return self.probabilities.pop(0) if self.probabilities else 0.0
