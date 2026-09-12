"""Debouncing a speech-likelihood signal into a stable verdict.

Every voice activity detector produces some continuous measure -- an amplitude,
a neural probability -- that hovers around its threshold and makes the verdict
flicker several times a second. Left unfiltered that flicker would reach the
turn detector, and every component downstream would have to defend against it.

The same state machine serves both detectors, which is why it lives on its own
rather than being written twice.
"""


class SpeechGate:
    """Two-threshold state machine with a release delay.

    Speech starts when the level crosses ``activation`` and ends only after the
    level has stayed below ``deactivation`` for ``hangover_ms``. Two thresholds
    rather than one because a single threshold makes the verdict oscillate for
    any level sitting on it.

    Args:
        activation: level at or above which speech begins.
        deactivation: level below which the release delay starts counting. Must
            not exceed ``activation``.
        hangover_ms: quiet time required before speech is declared over.

    Raises:
        ValueError: if ``deactivation`` exceeds ``activation``, which would make
            the gate oscillate rather than debounce.
    """

    def __init__(self, *, activation: float, deactivation: float, hangover_ms: int) -> None:
        if deactivation > activation:
            raise ValueError(
                f"deactivation ({deactivation}) must not exceed activation ({activation})"
            )
        self._activation = activation
        self._deactivation = deactivation
        self._hangover_ms = hangover_ms
        self._active = False
        self._quiet_ms = 0

    @property
    def active(self) -> bool:
        """Whether speech is currently considered to be in progress."""
        return self._active

    def update(self, level: float, *, elapsed_ms: int) -> bool:
        """Fold one measurement in and return the debounced verdict.

        Args:
            level: the detector's speech likelihood for this step.
            elapsed_ms: time this measurement covers, used to time the hangover.

        Returns:
            Whether speech is in progress after this measurement.
        """
        if self._active:
            self._quiet_ms = 0 if level >= self._deactivation else self._quiet_ms + elapsed_ms
            if self._quiet_ms >= self._hangover_ms:
                self._active = False
        elif level >= self._activation:
            self._active = True
            self._quiet_ms = 0
        return self._active

    def reset(self) -> None:
        """Forget the current run."""
        self._active = False
        self._quiet_ms = 0
