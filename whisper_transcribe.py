"""Transcribe audio files using OpenAI Whisper."""
import pathlib
import sys
import warnings

try:
    import whisper
except ImportError:
    whisper = None

_model_cache = {}


def transcribe(audio_path: pathlib.Path, model_name: str = "base") -> tuple:
    """Returns (transcribed_text, detected_language)."""
    if whisper is None:
        raise ImportError(
            "openai-whisper is not installed. Install with: pip install openai-whisper"
        )

    if model_name not in _model_cache:
        _model_cache[model_name] = whisper.load_model(model_name)
    model = _model_cache[model_name]

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")
        result = model.transcribe(str(audio_path))
    segments = result.get("segments", [])
    if segments:
        text = "\n".join(seg["text"].strip() for seg in segments if seg["text"].strip())
    else:
        text = result.get("text", "").strip()
    language = result.get("language", "unknown")
    return text, language


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python whisper_transcribe.py <audio_file> [model_name]")

    audio = pathlib.Path(sys.argv[1])
    model = sys.argv[2] if len(sys.argv) > 2 else "base"

    text, lang = transcribe(audio, model)
    print(f"Language: {lang}\n")
    print(text)
