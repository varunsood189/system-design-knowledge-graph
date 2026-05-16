"""Extract clean article text from engineering blog URLs."""

from urllib.parse import urlparse

import trafilatura

from backend.models import ExtractedArticle

MAX_TEXT_CHARS = 8000


def extract_article(url: str) -> ExtractedArticle:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Could not download content from {url}")

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or len(text.strip()) < 100:
        raise ValueError(f"Could not extract meaningful text from {url}")

    metadata = trafilatura.extract_metadata(downloaded)
    title = (metadata.title if metadata and metadata.title else "") or url

    clean = text.strip()
    if len(clean) > MAX_TEXT_CHARS:
        clean = clean[:MAX_TEXT_CHARS] + "\n...[truncated]"

    return ExtractedArticle(url=url, title=title.strip(), text=clean)
