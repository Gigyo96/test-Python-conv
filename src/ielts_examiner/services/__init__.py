"""External services, behind narrow protocols.

Every call to Google -- speech recognition, speech synthesis, the language model
-- goes through one of the three protocols in ``protocols``. Two things follow:
the whole test suite runs without a credential, and replacing a provider means
writing one module rather than touching the graphs.
"""

from ielts_examiner.services.protocols import (
    LanguageModel,
    SpeechToText,
    TextToSpeech,
    TranscriptUpdate,
    Word,
)

__all__ = ["LanguageModel", "SpeechToText", "TextToSpeech", "TranscriptUpdate", "Word"]
