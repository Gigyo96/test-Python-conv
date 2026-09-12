"""Silero voice activity detection: the production detector.

Silero is a small neural VAD that holds up on the hesitant, accented, non-native
speech this system exists to listen to, where an amplitude threshold does not.

The module is split so that the part worth testing is testable. :class:`SileroVad`
owns windowing and debouncing and is exercised against a stub; :class:`SileroModel`
is the thin ONNX boundary, which can only be verified against real speech.
"""

from pathlib import Path
from typing import Protocol

import numpy as np

from ielts_examiner.audio.frames import SAMPLE_RATE, AudioFrame
from ielts_examiner.audio.hysteresis import SpeechGate

MODEL_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/master/"
    "src/silero_vad/data/silero_vad.onnx"
)
"""Where to obtain the model. Quoted in the error raised when it is missing."""

WINDOW_SAMPLES = 512
"""Window the model expects at 16 kHz. Not negotiable: other sizes are rejected."""

WINDOW_MS = WINDOW_SAMPLES * 1000 // SAMPLE_RATE

_STATE_SHAPE = (2, 1, 128)
_INT16_FULL_SCALE = 32768.0


class SpeechProbabilityModel(Protocol):
    """Scores one window of audio for the presence of speech."""

    def probability(self, window: np.ndarray) -> float:
        """Likelihood in ``[0.0, 1.0]`` that ``window`` contains speech."""
        ...


class SileroModel:
    """The ONNX model, carrying its recurrent state across windows."""

    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Silero VAD model not found at {model_path}.\n"
                f"Download it once with:\n  curl -sSL -o {model_path} {MODEL_URL}"
            )
        import onnxruntime  # imported lazily: only this detector needs it

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        self._sample_rate = np.array(SAMPLE_RATE, dtype=np.int64)
        self._state = np.zeros(_STATE_SHAPE, dtype=np.float32)

    def probability(self, window: np.ndarray) -> float:
        """Score one ``WINDOW_SAMPLES`` window of float samples in ``[-1, 1]``."""
        output, self._state = self._session.run(
            None,
            {
                "input": window.reshape(1, WINDOW_SAMPLES),
                "state": self._state,
                "sr": self._sample_rate,
            },
        )
        return float(output[0][0])

    def reset(self) -> None:
        """Clear the recurrent state, at the start of a new turn."""
        self._state = np.zeros(_STATE_SHAPE, dtype=np.float32)


class SileroVad:
    """Neural voice activity detection over the system's 20 ms frames.

    The model consumes 512-sample windows while everything else works in 20 ms
    frames. Reconciling the two is this adapter's job: samples accumulate until a
    window is full, so a verdict refreshes roughly every 32 ms and is held in
    between. The lag is below the shortest threshold in the system and far below
    human reaction time.
    """

    def __init__(
        self,
        model: SpeechProbabilityModel,
        *,
        activation: float = 0.50,
        deactivation: float = 0.35,
        hangover_ms: int = 120,
    ) -> None:
        self._model = model
        self._gate = SpeechGate(
            activation=activation, deactivation=deactivation, hangover_ms=hangover_ms
        )
        self._pending = np.zeros(0, dtype=np.float32)

    @classmethod
    def load(cls, model_path: Path, **options: float) -> "SileroVad":
        """Build a detector around the model file at ``model_path``.

        Raises:
            FileNotFoundError: if the model is absent, with the download command
                in the message. Silently falling back to a cruder detector would
                change how the exam listens without saying so.
        """
        return cls(SileroModel(model_path), **options)  # type: ignore[arg-type]

    def is_speech(self, frame: AudioFrame) -> bool:
        """Classify ``frame``, scoring any complete windows it completes."""
        self._pending = np.concatenate(
            [self._pending, frame.samples.astype(np.float32) / _INT16_FULL_SCALE]
        )
        while self._pending.size >= WINDOW_SAMPLES:
            window, self._pending = self._pending[:WINDOW_SAMPLES], self._pending[WINDOW_SAMPLES:]
            self._gate.update(self._model.probability(window), elapsed_ms=WINDOW_MS)
        return self._gate.active

    def reset(self) -> None:
        """Forget buffered samples, the current run and the model's state."""
        self._pending = np.zeros(0, dtype=np.float32)
        self._gate.reset()
        if isinstance(self._model, SileroModel):
            self._model.reset()
