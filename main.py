"""CLI for converting epub chapters to narrated MP3."""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Union

from epub import extract_chapter, list_chapters
from tts import narrate

DEBUG_WORD_LIMIT = 100


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
    if not args.epub.exists():
        print(f"Error: file not found: {args.epub}", file=sys.stderr)
        sys.exit(1)

    if args.chapter is None:
        chapters = list_chapters(args.epub)
        if not chapters:
            print("No chapters found.", file=sys.stderr)
            sys.exit(1)
        for num, title in chapters:
            print(f"  {num:3d}. {title}")
        return

    try:
        chapter = extract_chapter(args.epub, args.chapter)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Text is: title \n\n para1 \n\n para2 ...
    parts = chapter.text.split("\n\n")
    first_two = [p for p in parts[1:] if p.strip()][:2]

    md = (
        f"# {chapter.title}\n\n"
        f"**Chapter {chapter.number}** · **{len(chapter.text):,} characters**\n\n"
        "---\n\n"
        + "\n\n".join(first_two)
    )
    _render_markdown(md)


def _cmd_create(args: argparse.Namespace) -> None:
    if not args.epub.exists():
        print(f"Error: file not found: {args.epub}", file=sys.stderr)
        sys.exit(1)

    try:
        chapter = extract_chapter(args.epub, args.chapter)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Chapter: {chapter.title}", file=sys.stderr)

    text = chapter.text
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert epub chapters to narrated MP3.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ── inspect ──────────────────────────────────────────────────────────────
    inspect = subparsers.add_parser(
        "inspect",
        help="Preview a chapter's text before generating audio",
        description=(
            "Show chapter name, character count, and first two paragraphs.\n"
            "Omit CHAPTER to list all chapters in the epub."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    inspect.add_argument("epub", type=Path, help="Path to the epub file")
    inspect.add_argument(
        "chapter",
        type=_chapter_arg,
        nargs="?",
        help="Chapter number (1-based) or title substring. Omit to list all chapters.",
    )

    # ── create ───────────────────────────────────────────────────────────────
    create = subparsers.add_parser(
        "create",
        help="Convert a chapter to a narrated MP3",
        description=(
            "Available voices:\n"
            "  Male:   Charon, Orus, Algenib, Rasalgethi\n"
            "  Female: Kore, Leda, Autonoe, Aoede"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    create.add_argument("epub", type=Path, help="Path to the epub file")
    create.add_argument(
        "chapter",
        type=_chapter_arg,
        help="Chapter number (1-based) or title substring",
    )
    create.add_argument("output", type=Path, help="Output MP3 path")
    create.add_argument(
        "--voice",
        default="Charon",
        metavar="NAME",
        help="TTS voice name (default: Charon)",
    )
    create.add_argument(
        "--start-chunk",
        type=int,
        metavar="N",
        help="Resume from chunk N (1-based)",
    )
    create.add_argument(
        "--end-chunk",
        type=int,
        metavar="N",
        help="Stop after chunk N (1-based)",
    )
    create.add_argument(
        "--debug",
        action="store_true",
        help=f"Generate audio for only the first {DEBUG_WORD_LIMIT} words (for testing)",
    )
    create.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.command == "inspect":
        _cmd_inspect(args)
    else:
        _cmd_create(args)


if __name__ == "__main__":
    main()
