# podcaster

Convert epub chapters to narrated MP3 using Google Gemini TTS.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — package manager
- [ffmpeg](https://ffmpeg.org/) — audio processing (`brew install ffmpeg`)
- Google Gemini API key

## Setup

```bash
# Install dependencies
uv sync

# Set your API key — either export it:
export GEMINI_API_KEY=your_key_here

# Or add it to ~/.podcaster/.env (auto-loaded on every run):
echo "GEMINI_API_KEY=your_key_here" >> ~/.podcaster/.env
```

## Usage

```
podcaster COMMAND [options]

Commands:
  inspect    Preview a chapter's text before generating audio
  create     Convert a chapter to a narrated MP3
  sources    Manage registered epub sources
```

---

### `inspect` — Preview chapters

```bash
# List all chapters in an epub
podcaster inspect book.epub

# Preview a chapter by number
podcaster inspect book.epub 3

# Preview a chapter by title substring (case-insensitive)
podcaster inspect book.epub "Introduction"

# Resolve by registered source ID or name
podcaster inspect abc12345 3
podcaster inspect "Moby Dick" 3
```

Output is rendered with [glow](https://github.com/charmbracelet/glow) if installed (`brew install glow`), otherwise plain text.

---

### `create` — Generate audio

```bash
# Convert chapter 3 to MP3
podcaster create book.epub 3 chapter3.mp3

# Specify a voice (default: Charon)
podcaster create book.epub 3 chapter3.mp3 --voice Kore

# Debug mode: only first 100 words (fast API test)
podcaster create book.epub 3 chapter3.mp3 --debug

# Resume from a specific chunk (e.g. after a failure)
podcaster create book.epub 3 chapter3.mp3 --start-chunk 5

# Process only a range of chunks
podcaster create book.epub 3 chapter3.mp3 --start-chunk 5 --end-chunk 10

# Verbose output (shows chunk progress)
podcaster create book.epub 3 chapter3.mp3 --verbose

# Resolve source by registered ID or name
podcaster create abc12345 3 chapter3.mp3
podcaster create "Moby Dick" 3 chapter3.mp3
```

#### Available voices

| Gender | Voice names                                |
|--------|--------------------------------------------|
| Male   | Charon (default), Orus, Algenib, Rasalgethi |
| Female | Kore, Leda, Autonoe, Aoede                 |

---

### `sources` — Registered epub registry

Register epub files once so you can refer to them by ID or name instead of typing full paths.

```bash
# Register an epub
podcaster sources add ~/Downloads/moby-dick.epub
# → Added: Moby Dick  (id: abc12345)

# List all registered sources
podcaster sources list
# → ID        Name       Path
# → --------  ---------  --------------------------------
# → abc12345  Moby Dick  ~/Downloads/moby-dick.epub

# Rename a source (by ID or name substring)
podcaster sources rename abc12345 "Moby Dick (Annotated)"
podcaster sources rename "Moby" "Moby Dick (Annotated)"

# Use a source by ID in any command
podcaster inspect abc12345
podcaster create abc12345 3 chapter3.mp3

# Use a source by name substring (case-insensitive)
podcaster inspect "Moby" 3
podcaster create "Moby" 3 chapter3.mp3 --voice Kore
```

The registry is stored at `~/.podcaster/sources.db`.

---

## How it works

1. **Extraction** (`epub.py`): Reads the epub spine in reading order using ebooklib + BeautifulSoup. Extracts headings and paragraph text.
2. **Chunking** (`tts.py`): Splits text at paragraph boundaries into ~500-word chunks to fit within API limits.
3. **TTS** (`tts.py`): Sends each chunk to `gemini-2.5-flash-preview-tts`, receiving raw PCM audio (mono, 16-bit, 24 kHz).
4. **Cache** (`tts.py`): Saves each chunk as a WAV file under `~/.podcaster/<md5-12char>/chunk_NNNN.wav`. Resuming skips cached chunks.
5. **Merge** (`tts.py`): Concatenates all WAV chunks and exports to MP3 via pydub/ffmpeg.

## File layout

```
podcaster/
├── main.py        # CLI (argparse subcommands)
├── epub.py        # EPUB extraction
├── tts.py         # TTS API, chunking, caching, merge
├── db.py          # Source registry (SQLite)
└── pyproject.toml
```

## Data directories

| Path | Contents |
|------|----------|
| `~/.podcaster/sources.db` | Registered epub sources |
| `~/.podcaster/.env` | Environment variables (e.g. `GEMINI_API_KEY`) |
| `~/.podcaster/<md5>/chunk_NNNN.wav` | Cached WAV chunks per unique text |
