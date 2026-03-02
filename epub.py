"""EPUB chapter extraction and text formatting."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub


@dataclass
class Chapter:
    title: str
    number: int  # 1-based index in spine
    text: str  # formatted plain text ready for TTS


def _spine_items(book: epub.EpubBook) -> list[epub.EpubItem]:
    """Return document items in spine (reading) order."""
    spine_ids = [item_id for item_id, _ in book.spine]
    by_id = {
        item.get_id(): item
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
    }
    return [by_id[id_] for id_ in spine_ids if id_ in by_id]


def _parse_html(content: bytes) -> tuple[str, str]:
    """Parse HTML content into (heading, body_text).

    Returns the first heading tag's text and all paragraph text joined
    by double newlines.
    """
    soup = BeautifulSoup(content, "html.parser")

    heading = ""
    heading_tag = soup.find(re.compile(r"^h[1-6]$"))
    if heading_tag:
        heading = heading_tag.get_text(strip=True)
        heading_tag.decompose()

    paragraphs = [
        p.get_text(strip=True)
        for p in soup.find_all("p")
        if p.get_text(strip=True)
    ]

    return heading, "\n\n".join(paragraphs)


def _format_chapter(title: str, body: str) -> str:
    """Join title and body with double newline, omitting blank parts."""
    parts = [p for p in (title, body) if p]
    return "\n\n".join(parts)


def epub_title(epub_path: Path) -> str:
    """Return the epub's title metadata, falling back to the filename stem."""
    book = epub.read_epub(str(epub_path))
    return (book.title or "").strip() or epub_path.stem


def list_chapters(epub_path: Path) -> list[tuple[int, str]]:
    """Return [(number, title), ...] for all chapters in reading order."""
    book = epub.read_epub(str(epub_path))
    items = _spine_items(book)
    result = []
    for i, item in enumerate(items, start=1):
        heading, _ = _parse_html(item.get_content())
        result.append((i, heading or item.get_name()))
    return result


def extract_chapter(epub_path: Path, chapter: Union[int, str]) -> Chapter:
    """Extract a chapter by 1-based number or title substring (case-insensitive).

    Args:
        epub_path: Path to the epub file.
        chapter: Chapter number (1-based) or substring of the chapter title.

    Returns:
        Chapter with title, spine number, and formatted plain text.

    Raises:
        ValueError: If the chapter is out of range or no title match is found.
    """
    book = epub.read_epub(str(epub_path))
    items = _spine_items(book)

    if not items:
        raise ValueError("No document items found in epub")

    if isinstance(chapter, int):
        if not 1 <= chapter <= len(items):
            raise ValueError(
                f"Chapter {chapter} out of range (1–{len(items)})"
            )
        item = items[chapter - 1]
        heading, body = _parse_html(item.get_content())
        title = heading or item.get_name()
        return Chapter(title=title, number=chapter, text=_format_chapter(title, body))

    # Search by title substring
    query = chapter.casefold()
    for i, item in enumerate(items, start=1):
        heading, body = _parse_html(item.get_content())
        title = heading or item.get_name()
        if query in title.casefold() or query in item.get_name().casefold():
            return Chapter(title=title, number=i, text=_format_chapter(title, body))

    raise ValueError(f"No chapter matching '{chapter}' found")
