"""Voice activity detection.

The detector owns *debouncing* as well as detection. That is a deliberate
division of labour: raw frame-by-frame verdicts flicker, and if the flicker
reached the turn detector every component downstream would have to defend
against it. Absorbing it here keeps ``turntaking.detector`` to pure bookkeeping.

``EnergyVad`` is the development implementation. Silero arrives in M2 behind the
same protocol; nothing above this module changes when it does.
"""

from typing import Protocol

from ielts_examiner.audio.frames import FRAME_MS, AudioFrame


class VoiceActivityDetector(Protocol):
    """Classifies frames as speech or silence, with hysteresis."""

    def is_speech(self, frame: AudioFrame) -> bool:
        """Whether ``frame`` is part of an ongoing speech run."""
        ...

    def reset(self) -> None:
        """Drop internal state, at the start of a new turn."""
        ...


class EnergyVad:
    """Amplitude-threshold detector with asymmetric thresholds and a hangover.

    Crude but predictable, which is what a development and replay implementation
    should be: given the same audio it always produces the same verdicts, so a
    change in endpointing behaviour during replay can only come from the policy.

    Two thresholds rather than one, because a single threshold makes speech
    flicker on and off around its value. Speech must cross ``activation_rms`` to
    start and stay below ``deactivation_rms`` for ``hangover_ms`` to stop.
    """

    def __init__(
        self,
        *,
        activation_rms: float = 0.020,
        deactivation_rms: float = 0.010,
        hangover_ms: int = 60,
    ) -> None:
        self._activation_rms = activation_rms
        self._deactivation_rms = deactivation_rms
        self._hangover_ms = hangover_ms
        self._active = False
        self._quiet_ms = 0

    def is_speech(self, frame: AudioFrame) -> bool:
        """Classify ``frame``, taking the preceding frames into account."""
        rms = frame.rms
        if self._active:
            self._quiet_ms = 0 if rms >= self._deactivation_rms else self._quiet_ms + FRAME_MS
            if self._quiet_ms >= self._hangover_ms:
                self._active = False
        elif rms >= self._activation_rms:
            self._active = True
            self._quiet_ms = 0
        return self._active

    def reset(self) -> None:
        """Forget the current speech run."""
        self._active = False
        self._quiet_ms = 0
