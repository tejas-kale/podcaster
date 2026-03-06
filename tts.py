"""Gemini TTS: chunk text, call API, cache WAV chunks, merge to MP3."""

import hashlib
import os
import sys
import time
import wave
from pathlib import Path

from google import genai
from google.genai import types
from pydub import AudioSegment

CACHE_ROOT = Path.home() / ".podcaster"
CHUNK_MAX_WORDS = 500
TTS_MODEL = "gemini-2.5-flash-preview-tts"
CLEAN_MODEL = "gemini-3-flash-preview"

# Fixed PCM format returned by the Gemini TTS API — do not infer from response
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2  # 16-bit
PCM_FRAME_RATE = 24000  # 24 kHz


def _log(message: str, *, verbose: bool, force: bool = False) -> None:
    if verbose or force:
        print(message, file=sys.stderr)


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _chunk_text(text: str, max_words: int = CHUNK_MAX_WORDS) -> list[str]:
    """Split text into chunks at paragraph boundaries, each ≤ max_words."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        word_count = len(para.split())
        if current and current_words + word_count > max_words:
            chunks.append("\n\n".join(current))
            current = [para]
            current_words = word_count
        else:
            current.append(para)
            current_words += word_count

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _pcm_to_wav(pcm_data: bytes, wav_path: Path) -> None:
    """Write raw PCM bytes as a WAV file (mono, 16-bit, 24 kHz)."""
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(PCM_CHANNELS)
        wf.setsampwidth(PCM_SAMPLE_WIDTH)
        wf.setframerate(PCM_FRAME_RATE)
        wf.writeframes(pcm_data)


def _generate_chunk(
    client: genai.Client,
    text: str,
    voice: str,
    wav_path: Path,
    *,
    verbose: bool,
) -> None:
    """Call Gemini TTS for one text chunk, write result to wav_path.

    Retries once after a 5-second wait on failure.
    """
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=TTS_MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice
                            )
                        )
                    ),
                ),
            )
            pcm_data = response.candidates[0].content.parts[0].inline_data.data
            _pcm_to_wav(pcm_data, wav_path)
            return
        except Exception as e:
            if attempt == 0:
                _log(
                    f"  Attempt 1 failed: {e}. Retrying in 5s...",
                    verbose=verbose,
                    force=True,
                )
                time.sleep(5)
            else:
                raise


def _merge_wav_to_mp3(wav_paths: list[Path], output_path: Path) -> None:
    """Concatenate WAV chunks and export as MP3."""
    audio = AudioSegment.empty()
    for wav_path in wav_paths:
        audio += AudioSegment.from_wav(str(wav_path))
    audio.export(str(output_path), format="mp3")


def clean_text(text: str, *, verbose: bool = False) -> str:
    """Use Gemini to clean up text formatting (joined words, artifacts) verbatim."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")

    client = genai.Client(api_key=api_key)
    _log("Cleaning text with Gemini...", verbose=verbose, force=True)

    prompt = (
        "The following text was extracted from an EPUB and has some formatting issues "
        "like joined words (e.g., 'hewould' instead of 'he would') and weird characters. "
        "Please return the content verbatim but properly formatted. "
        "Do not change the wording. Do not add any preamble or postamble. "
        "Use exactly ONE empty line between paragraphs. "
        "Return ONLY the cleaned text.\n\n"
        f"TEXT:\n---\n{text}\n---"
    )

    try:
        response = client.models.generate_content(
            model=CLEAN_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        _log(f"Warning: Text cleaning failed ({e}). Using raw text.", verbose=verbose, force=True)
        return text


def narrate(
    text: str,
    output_path: Path,
    *,
    voice: str = "Charon",
    verbose: bool = False,
    start_chunk: int | None = None,
    end_chunk: int | None = None,
) -> None:
    """Convert text to a narrated MP3 using Gemini TTS.

    Caches WAV chunks under ~/.podcaster/<hash>/ so a failed run can be
    resumed without re-generating completed chunks.

    Args:
        text: Full text to narrate.
        output_path: Destination MP3 path.
        voice: Gemini TTS prebuilt voice name.
        verbose: Print debug info to stderr.
        start_chunk: Resume from this chunk number (1-based, inclusive).
        end_chunk: Stop after this chunk number (1-based, inclusive).

    Raises:
        ValueError: If GEMINI_API_KEY is not set.
        RuntimeError: If any chunks fail after retries, or chunks are missing at merge time.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")

    client = genai.Client(api_key=api_key)
    chunks = _chunk_text(text)
    total = len(chunks)

    cache_dir = CACHE_ROOT / _cache_key(text + voice)
    cache_dir.mkdir(parents=True, exist_ok=True)

    _log(
        f"Text: {len(text.split())} words → {total} chunk(s)",
        verbose=verbose,
        force=True,
    )
    _log(f"Cache: {cache_dir}", verbose=verbose)
    _log(f"Voice: {voice}", verbose=verbose)

    range_start = start_chunk or 1
    range_end = end_chunk or total

    failed: list[int] = []

    for i, chunk in enumerate(chunks):
        chunk_num = i + 1
        wav_path = cache_dir / f"chunk_{chunk_num:04d}.wav"

        if not (range_start <= chunk_num <= range_end):
            continue

        if wav_path.exists():
            _log(f"  Chunk {chunk_num}/{total}: cached", verbose=verbose)
            continue

        _log(f"  Chunk {chunk_num}/{total}: generating...", verbose=verbose, force=True)
        try:
            _generate_chunk(client, chunk, voice, wav_path, verbose=verbose)
            _log(f"  Chunk {chunk_num}/{total}: done", verbose=verbose)
        except Exception as e:
            _log(
                f"  Chunk {chunk_num}/{total}: FAILED — {e}",
                verbose=verbose,
                force=True,
            )
            failed.append(chunk_num)

    if failed:
        raise RuntimeError(
            f"Failed chunk(s): {failed}. "
            "Re-run with --start-chunk / --end-chunk to regenerate them."
        )

    # Merge only when all chunks are present; otherwise report what's still needed
    all_wavs = [cache_dir / f"chunk_{i + 1:04d}.wav" for i in range(total)]
    missing = [i + 1 for i, wav in enumerate(all_wavs) if not wav.exists()]
    if missing:
        _log(
            f"Chunks {range_start}–{range_end} done. "
            f"Still needed: {missing}. "
            "Re-run with --start-chunk / --end-chunk to generate them.",
            verbose=verbose,
            force=True,
        )
        return

    _log("Merging chunks...", verbose=verbose, force=True)
    _merge_wav_to_mp3(all_wavs, output_path)

    for wav in all_wavs:
        wav.unlink()
    cache_dir.rmdir()

    _log(f"Done: {output_path}", verbose=verbose, force=True)
    print(str(output_path))
