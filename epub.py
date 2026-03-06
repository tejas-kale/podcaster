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
    """Parse HTML content into (heading, body_markdown).

    Extracts the first heading as the title, then converts common
    HTML tags to markdown.
    """
    soup = BeautifulSoup(content, "html.parser")

    # 1. Extract the first heading for the title
    heading = ""
    heading_tag = soup.find(re.compile(r"^h[1-6]$"))
    if heading_tag:
        heading = heading_tag.get_text(strip=True)
        # We don't decompose() it yet if we want it in the body markdown too,
        # but the current logic seems to treat it separately.
        # Let's decompose it to avoid duplication if it's used as 'title'.
        heading_tag.decompose()

    # 2. Convert common inline tags
    for tag in soup.find_all(["b", "strong"]):
        tag.replace_with(f"**{tag.get_text()}**")
    for tag in soup.find_all(["i", "em"]):
        tag.replace_with(f"*{tag.get_text()}*")
    for tag in soup.find_all("a"):
        href = tag.get("href", "")
        if href:
            tag.replace_with(f"[{tag.get_text()}]({href})")
        else:
            tag.unwrap()

    # 3. Handle block elements
    # We'll collect all top-level blocks and format them
    blocks = []

    # Common block tags in EPUBs
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"]):
        text = tag.get_text(strip=True)
        if not text:
            continue

        name = tag.name
        if name.startswith("h"):
            level = int(name[1])
            blocks.append(f"{'#' * level} {text}")
        elif name == "li":
            # Simple bullet for list items
            blocks.append(f"- {text}")
        elif name == "blockquote":
            blocks.append(f"> {text}")
        else:
            # Paragraphs
            blocks.append(text)

    body = "\n\n".join(blocks)
    # Collapse any existing triple+ newlines just in case
    body = re.sub(r"\n{3,}", "\n\n", body)
    return heading, body


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
