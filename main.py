"""CLI for converting epub chapters to narrated MP3."""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Union

import db
from epub import epub_title, extract_chapter, list_chapters
from tejas_config import get_secret as _get_secret
from tts import clean_text, narrate

DEBUG_WORD_LIMIT = 100


def _load_env() -> None:
    """Inject credentials from tejas-config keyring into os.environ."""
    key = _get_secret("gemini_api_key")
    if key:
        os.environ.setdefault("GEMINI_API_KEY", key)


def _resolve_epub(query: str) -> Path:
    """Resolve an epub path or registered source ID/name.

    Args:
        query: A file path, source ID, or source name substring.

    Returns:
        Absolute path to the epub file.

    Raises:
        ValueError: If no file or registered source matches.
    """
    p = Path(query).expanduser()
    if p.exists():
        return p
    source = db.find_source(query)
    if source:
        return Path(source.path)
    raise ValueError(f"No epub file or source matching '{query}'")


def _chapter_arg(value: str) -> Union[int, str]:
    """Accept a chapter number or title substring."""
    try:
        return int(value)
    except ValueError:
        return value


def _render_markdown(md: str) -> None:
    """Pipe markdown to glow; fall back to plain print if glow is not found."""
    try:
        subprocess.run(["glow", "-"], input=md.encode(), check=True)
    except FileNotFoundError:
        print("(glow not found — install with: brew install glow)\n", file=sys.stderr)
        print(md)


def _cmd_inspect(args: argparse.Namespace) -> None:
    try:
        epub_path = _resolve_epub(args.epub)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.chapter is None:
        chapters = list_chapters(epub_path)
        if not chapters:
            print("No chapters found.", file=sys.stderr)
            sys.exit(1)
        for num, title in chapters:
            print(f"  {num:3d}. {title}")
        return

    try:
        chapter = extract_chapter(epub_path, args.chapter)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    text = chapter.text
    if args.clean:
        text = clean_text(text, verbose=args.verbose)

    # Text is: title \n\n para1 \n\n para2 ...
    parts = text.split("\n\n")
    if args.full:
        content = "\n\n".join(p for p in parts[1:] if p.strip())
    else:
        first_two = [p for p in parts[1:] if p.strip()][:2]
        content = "\n\n".join(first_two)

    md = (
        f"# {chapter.title}\n\n"
        f"**Chapter {chapter.number}** · **{len(text):,} characters**\n\n"
        "---\n\n"
        + content
    )
    _render_markdown(md)


def _cmd_create(args: argparse.Namespace) -> None:
    try:
        epub_path = _resolve_epub(args.epub)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        chapter = extract_chapter(epub_path, args.chapter)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Chapter: {chapter.title}", file=sys.stderr)

    text = chapter.text
    if args.clean:
        text = clean_text(text, verbose=args.verbose)

    if args.debug:
        words = text.split()[:DEBUG_WORD_LIMIT]
        text = " ".join(words)
        print(
            f"Debug mode: using first {len(words)} words of {len(chapter.text.split())}",
            file=sys.stderr,
        )

    try:
        narrate(
            text,
            args.output,
            voice=args.voice,
            verbose=args.verbose,
            start_chunk=args.start_chunk,
            end_chunk=args.end_chunk,
        )
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_sources_add(args: argparse.Namespace) -> None:
    p = Path(args.epub).expanduser().resolve()
    if not p.exists():
        print(f"Error: file not found: {p}", file=sys.stderr)
        sys.exit(1)
    name = epub_title(p)
    source = db.add_source(p, name)
    print(f"Added: {source.name}  (id: {source.id})")


def _cmd_sources_rename(args: argparse.Namespace) -> None:
    source = db.rename_source(args.source, args.name)
    if source is None:
        print(f"Error: no source matching '{args.source}'", file=sys.stderr)
        sys.exit(1)
    print(f"Renamed: {source.name}  (id: {source.id})")


def _cmd_sources_list(args: argparse.Namespace) -> None:
    sources = db.list_sources()
    if not sources:
        print("No sources registered. Use 'podcaster sources add <epub>' to add one.")
        return

    home = str(Path.home())
    # Column widths
    id_w = max(len("ID"), max(len(s.id) for s in sources))
    name_w = max(len("Name"), max(len(s.name) for s in sources))

    header = f"{'ID':<{id_w}}  {'Name':<{name_w}}  Path"
    print(header)
    print("-" * min(len(header) + 20, 100))
    for s in sources:
        path = s.path.replace(home, "~", 1)
        print(f"{s.id:<{id_w}}  {s.name:<{name_w}}  {path}")


def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(
        description="Convert epub chapters to narrated MP3 using Gemini TTS.",
        epilog=(
            "EPUB resolution order (used by inspect and create):\n"
            "  1. File path (absolute or relative, ~ expanded)\n"
            "  2. Registered source ID (exact match)\n"
            "  3. Registered source name (case-insensitive substring)\n"
            "\n"
            "Credentials:\n"
            "  Set GEMINI_API_KEY as an environment variable, or configure it\n"
            "  via tejas-config under the 'podcaster' profile.\n"
            "\n"
            "Examples:\n"
            "  podcaster sources add ~/Downloads/book.epub\n"
            "  podcaster inspect abc12345\n"
            "  podcaster create abc12345 3 ch3.mp3\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ── inspect ──────────────────────────────────────────────────────────────
    inspect = subparsers.add_parser(
        "inspect",
        help="Preview a chapter's text before generating audio",
        description=(
            "When CHAPTER is omitted, lists all chapters with their spine numbers.\n"
            "When CHAPTER is given, shows the chapter title, total character count,\n"
            "and the first two paragraphs rendered as markdown (via glow if installed).\n"
            "\n"
            "Use --full to show the entire chapter text.\n"
            "\n"
            "EPUB may be a file path, a registered source ID, or a source name substring.\n"
            "Run 'podcaster sources list' to see registered sources."
        ),
        epilog=(
            "Examples:\n"
            "  podcaster inspect book.epub             # list all chapters\n"
            "  podcaster inspect book.epub 3           # preview chapter 3\n"
            "  podcaster inspect book.epub 3 --full    # show entire chapter\n"
            "  podcaster inspect book.epub Intro       # chapter whose title contains 'Intro'\n"
            "  podcaster inspect abc12345              # resolve by source ID\n"
            "  podcaster inspect \"Moby Dick\" 3         # resolve by source name substring\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    inspect.add_argument(
        "epub",
        type=str,
        help="Path to epub file, registered source ID, or source name substring",
    )
    inspect.add_argument(
        "chapter",
        type=_chapter_arg,
        nargs="?",
        help=(
            "Chapter number (1-based spine index) or case-insensitive title substring."
            " Omit to list all chapters."
        ),
    )
    inspect.add_argument(
        "--full",
        action="store_true",
        help="Show the entire chapter text instead of just a preview",
    )
    inspect.add_argument(
        "--clean",
        action="store_true",
        help="Use Gemini to clean up text formatting (fix joined words, artifacts)",
    )
    inspect.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print debug information to stderr",
    )

    # ── create ───────────────────────────────────────────────────────────────
    create = subparsers.add_parser(
        "create",
        help="Convert a chapter to a narrated MP3",
        description=(
            "Extracts the chapter text, splits it into ~500-word chunks, sends each\n"
            "chunk to Gemini TTS, and merges the results into a single MP3 file.\n"
            "\n"
            "Chunks are cached as WAV files under ~/.podcaster/<hash>/chunk_NNNN.wav.\n"
            "If the run is interrupted, use --start-chunk to resume without re-generating\n"
            "chunks that already completed.\n"
            "\n"
            "Available voices:\n"
            "  Male:   Charon (default), Orus, Algenib, Rasalgethi\n"
            "  Female: Kore, Leda, Autonoe, Aoede\n"
            "\n"
            "EPUB may be a file path, a registered source ID, or a source name substring.\n"
            "Run 'podcaster sources list' to see registered sources."
        ),
        epilog=(
            "Examples:\n"
            "  podcaster create book.epub 3 ch3.mp3\n"
            "  podcaster create book.epub Intro ch_intro.mp3 --voice Kore\n"
            "  podcaster create abc12345 3 ch3.mp3              # resolve by source ID\n"
            "  podcaster create \"Moby Dick\" 3 ch3.mp3           # resolve by source name\n"
            "  podcaster create book.epub 3 ch3.mp3 --debug     # test with first 100 words\n"
            "  podcaster create book.epub 3 ch3.mp3 --start-chunk 7  # resume after failure\n"
            "  podcaster create book.epub 3 ch3.mp3 --start-chunk 5 --end-chunk 10\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    create.add_argument(
        "epub",
        type=str,
        help="Path to epub file, registered source ID, or source name substring",
    )
    create.add_argument(
        "chapter",
        type=_chapter_arg,
        help="Chapter number (1-based spine index) or case-insensitive title substring",
    )
    create.add_argument("output", type=Path, help="Output MP3 file path")
    create.add_argument(
        "--voice",
        default="Charon",
        metavar="NAME",
        help=(
            "Gemini TTS voice name (default: Charon)."
            " Male: Charon, Orus, Algenib, Rasalgethi."
            " Female: Kore, Leda, Autonoe, Aoede."
        ),
    )
    create.add_argument(
        "--start-chunk",
        type=int,
        metavar="N",
        help=(
            "Start processing from chunk N (1-based), skipping earlier chunks."
            " Use this to resume after a failure; chunks before N must already be cached."
        ),
    )
    create.add_argument(
        "--end-chunk",
        type=int,
        metavar="N",
        help=(
            "Stop after processing chunk N (1-based), inclusive."
            " Combine with --start-chunk to process a specific range."
            " The final MP3 will contain only the processed chunks."
        ),
    )
    create.add_argument(
        "--debug",
        action="store_true",
        help=(
            f"Process only the first {DEBUG_WORD_LIMIT} words of the chapter."
            " Useful for quickly testing voice, API connectivity, or output format"
            " without waiting for a full chapter to render."
        ),
    )
    create.add_argument(
        "--clean",
        action="store_true",
        help="Use Gemini to clean up text formatting (fix joined words, artifacts)",
    )
    create.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print chunk-level progress (chunk number, word count, cache hits) to stderr.",
    )

    # ── sources ───────────────────────────────────────────────────────────────
    sources = subparsers.add_parser(
        "sources",
        help="Manage registered epub sources",
        description=(
            "Register epub files by path once, then refer to them by their auto-assigned\n"
            "ID or by a substring of their title in any inspect or create command.\n"
            "\n"
            "The registry is stored in ~/.podcaster/sources.db."
        ),
        epilog=(
            "Examples:\n"
            "  podcaster sources add ~/Downloads/book.epub\n"
            "  podcaster sources list\n"
            "  podcaster sources rename abc12345 \"Moby Dick (Annotated)\"\n"
            "  podcaster inspect abc12345 3         # use ID from sources list\n"
            "  podcaster create \"Moby\" 3 ch3.mp3   # use name substring\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src_sub = sources.add_subparsers(dest="sources_command", metavar="SUBCOMMAND")
    src_sub.required = True

    src_add = src_sub.add_parser(
        "add",
        help="Register an epub file",
        description=(
            "Registers the epub at the given path in ~/.podcaster/sources.db.\n"
            "The display name is read from the epub's title metadata; if the epub\n"
            "has no title, the filename stem is used instead.\n"
            "The path is stored as an absolute path, so the file must remain accessible\n"
            "at that location for future commands to work."
        ),
        epilog=(
            "Examples:\n"
            "  podcaster sources add ~/Downloads/moby-dick.epub\n"
            "  podcaster sources add /Volumes/Books/war-and-peace.epub\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src_add.add_argument("epub", type=str, help="Path to the epub file to register")

    src_sub.add_parser(
        "list",
        help="List all registered epub sources",
        description=(
            "Prints a table of all registered sources with their ID, title, and path.\n"
            "Home directory is shown as ~ for brevity.\n"
            "The ID can be passed directly to inspect or create instead of the full path."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    src_rename = src_sub.add_parser(
        "rename",
        help="Change the display name of a registered source",
        description=(
            "Updates the display name of a source identified by its ID or current name.\n"
            "The ID and stored path are not affected.\n"
            "\n"
            "SOURCE may be an exact source ID or a case-insensitive substring of the\n"
            "current name (same resolution used by inspect and create)."
        ),
        epilog=(
            "Examples:\n"
            "  podcaster sources rename abc12345 \"Moby Dick (Annotated)\"\n"
            "  podcaster sources rename \"Moby\" \"Moby Dick (Annotated)\"\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src_rename.add_argument(
        "source",
        type=str,
        help="Source ID (exact) or current name substring",
    )
    src_rename.add_argument("name", type=str, help="New display name")

    args = parser.parse_args()

    if args.command == "inspect":
        _cmd_inspect(args)
    elif args.command == "create":
        _cmd_create(args)
    elif args.command == "sources":
        if args.sources_command == "add":
            _cmd_sources_add(args)
        elif args.sources_command == "rename":
            _cmd_sources_rename(args)
        else:
            _cmd_sources_list(args)


if __name__ == "__main__":
    main()
