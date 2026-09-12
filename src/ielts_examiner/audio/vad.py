"""Voice activity detection.

Detectors own *debouncing* as well as detection: raw frame-by-frame verdicts
flicker, and absorbing that here keeps ``turntaking.detector`` to pure
bookkeeping. The shared state machine lives in :mod:`ielts_examiner.audio.hysteresis`.

``EnergyVad`` is the development implementation; :class:`~ielts_examiner.audio.silero.SileroVad`
is the production one. Nothing above this module changes between them.
"""

from typing import Protocol

from ielts_examiner.audio.frames import FRAME_MS, AudioFrame
from ielts_examiner.audio.hysteresis import SpeechGate


class VoiceActivityDetector(Protocol):
    """Classifies frames as speech or silence, with hysteresis."""

    def is_speech(self, frame: AudioFrame) -> bool:
        """Whether ``frame`` is part of an ongoing speech run."""
        ...

    def reset(self) -> None:
        """Drop internal state, at the start of a new turn."""
        ...


class EnergyVad:
    """Amplitude-threshold detector.

    Crude but predictable, which is what a development and replay detector
    should be: given the same audio it always produces the same verdicts, so a
    change in endpointing behaviour during replay can only come from the policy.

    It measures loudness, not voice. On synthetic noise it reports speech and a
    neural detector correctly does not -- which is why replay fixtures built
    from noise exercise this detector and never Silero.
    """

    def __init__(
        self,
        *,
        activation_rms: float = 0.020,
        deactivation_rms: float = 0.010,
        hangover_ms: int = 60,
    ) -> None:
        self._gate = SpeechGate(
            activation=activation_rms, deactivation=deactivation_rms, hangover_ms=hangover_ms
        )

    def is_speech(self, frame: AudioFrame) -> bool:
        """Classify ``frame``, taking the preceding frames into account."""
        return self._gate.update(frame.rms, elapsed_ms=FRAME_MS)

    def reset(self) -> None:
        """Forget the current speech run."""
        self._gate.reset()
