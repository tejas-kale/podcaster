# Podcaster: Approach & Learnings

A text-to-MP3 narrator using Gemini TTS. Single voice reads an article or story aloud.

Learnings drawn from `podcast-translator`, which has a production-grade Gemini TTS implementation.

---

## Goal

Take arbitrary text (article, story, essay) → produce a narrated MP3 with a single consistent voice.

---

## Gemini TTS API

### Model
`gemini-2.5-flash-preview-tts` — dedicated TTS model, not the general-purpose `gemini-*` models.

### Single-voice config
For a narrator (vs. multi-speaker podcast), use `VoiceConfig`, not `MultiSpeakerVoiceConfig`:

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model="gemini-2.5-flash-preview-tts",
    contents=text_chunk,
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Charon"  # or any voice below
                )
            )
        )
    )
)
```

### Available voices
From podcast-translator:
- Male: `Charon`, `Orus`, `Algenib`, `Rasalgethi`
- Female: `Kore`, `Leda`, `Autonoe`, `Aoede`

### Audio response format
- Comes back as raw PCM bytes in `response.candidates[0].content.parts[0].inline_data.data`
- Fixed format: mono (1 channel), 16-bit samples, 24 kHz sample rate
- Write to WAV using Python's `wave` module, then convert to MP3 with pydub

```python
import wave

with wave.open(str(wav_path), "wb") as wf:
    wf.setnchannels(1)     # mono
    wf.setsampwidth(2)     # 16-bit = 2 bytes
    wf.setframerate(24000) # 24 kHz
    wf.writeframes(pcm_data)
```

---

## Chunking Strategy

The TTS API has token limits. Long articles must be split into chunks.

### Recommended approach
- Split text on paragraph boundaries (double newlines)
- Group paragraphs until chunk reaches ~500 words
- This stays well within API limits while minimising the number of API calls

### Why not split mid-sentence?
Splitting mid-sentence causes unnatural pauses or incomplete phrasing at chunk boundaries. Always break at paragraph or sentence boundaries.

### Concatenation
After generating all chunks as WAV files, concatenate with pydub:

```python
from pydub import AudioSegment

audio = AudioSegment.empty()
for chunk_path in sorted(chunk_paths):
    audio += AudioSegment.from_wav(str(chunk_path))

audio.export(output_path, format="mp3")
```

---

## Caching & Resumption

Podcast-translator's approach works well and should be reused:

- Hash the full input text with MD5 (first 12 chars) to get a cache key
- Store chunks as `~/.podcaster/<hash>/chunk_0001.wav`, `chunk_0002.wav`, etc.
- On startup, skip chunks that already exist on disk
- If all chunks succeed, delete the cache directory automatically
- Expose `--start-chunk` / `--end-chunk` CLI flags for manual re-runs of specific chunks

This means a failed run can always be resumed without re-generating chunks that already worked.

---

## Retry Logic

From podcast-translator: 2 attempts per chunk, 5-second wait between attempts. Simple, effective.

```python
for attempt in range(2):
    try:
        # call API
        break
    except Exception as e:
        if attempt == 0:
            time.sleep(5)
```

Track failed chunks and report them at the end rather than raising immediately — this preserves partial results.

---

## CLI Design

Follow the same pattern as `podcast_create.py`:
- Accept text from a file (`--input-file`) or stdin
- Accept output MP3 path as positional arg
- `--voice` to pick narrator voice (default: `Charon`)
- `--start-chunk` / `--end-chunk` for resumption
- `-v` / `--verbose` for debug output
- Status → stderr, final result path → stdout

---

## Logging Pattern

```python
def _log(message: str, *, verbose: bool, force: bool = False) -> None:
    if verbose or force:
        print(message, file=sys.stderr)
```

- `force=True`: always show (progress milestones)
- `verbose=True`: show debug details
- stdout: reserved for the output file path only

---

## Environment

- `GEMINI_API_KEY` — required, no fallback
- Package manager: `uv`
- Python: 3.11+
- Key deps: `google-genai`, `pydub`

---

## Project Structure (proposed)

```
podcaster/
  pyproject.toml   # uv project, registers `podcaster` CLI command
  tts.py           # core logic: chunking, API calls, caching, merging
  main.py          # CLI wrapper (argparse → calls tts.py)
  .python-version  # 3.11
  .gitignore
```

Keeping logic in `tts.py` separate from the CLI in `main.py` makes it importable and testable independently.

---

## Gotchas from podcast-translator

1. **Export temp chunks as WAV, not MP3.** MP3 encoder delay/padding causes sample-count mismatches when concatenating. Always use uncompressed WAV for intermediate chunks.

2. **pydub MP3 export requires ffmpeg.** Ensure ffmpeg is installed (`brew install ffmpeg`). pydub itself won't error until export time.

3. **PCM data format is fixed.** Don't try to infer it from the response — it's always mono/16-bit/24kHz. Hard-code these in the `wave.open` call.

4. **Cache dir tied to input text hash.** If you modify the text and re-run, it gets a new cache dir and starts fresh. This is correct behaviour.

5. **Retry on any exception, not just rate limits.** The API can fail transiently for various reasons. A simple 2-attempt retry covers most cases without overcomplicating error handling.
