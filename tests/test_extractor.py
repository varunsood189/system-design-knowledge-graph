"""Article extraction tests."""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.extractor import MAX_TEXT_CHARS, extract_article
from backend.models import ExtractedArticle


SAMPLE_HTML = "<html><head><title>Test</title></head><body><p>" + ("word " * 200) + "</p></body></html>"
SAMPLE_TEXT = "word " * 200


def test_extract_article_success():
    meta = MagicMock()
    meta.title = "Test Post"

    with (
        patch("backend.extractor.trafilatura.fetch_url", return_value=SAMPLE_HTML),
        patch("backend.extractor.trafilatura.extract", return_value=SAMPLE_TEXT.strip()),
        patch("backend.extractor.trafilatura.extract_metadata", return_value=meta),
    ):
        article = extract_article("https://example.com/blog/post")

    assert article.title == "Test Post"
    assert len(article.text) >= 100
    assert article.url == "https://example.com/blog/post"


def test_extract_article_rejects_short_text():
    with (
        patch("backend.extractor.trafilatura.fetch_url", return_value=SAMPLE_HTML),
        patch("backend.extractor.trafilatura.extract", return_value="too short"),
        patch("backend.extractor.trafilatura.extract_metadata", return_value=None),
    ):
        with pytest.raises(ValueError, match="meaningful text"):
            extract_article("https://example.com/empty")


def test_extract_article_rejects_bad_url():
    with pytest.raises(ValueError, match="Invalid URL"):
        extract_article("not-a-url")


def test_extract_article_truncates_long_text():
    long_text = "x" * (MAX_TEXT_CHARS + 500)
    meta = MagicMock()
    meta.title = "Long"

    with (
        patch("backend.extractor.trafilatura.fetch_url", return_value=SAMPLE_HTML),
        patch("backend.extractor.trafilatura.extract", return_value=long_text),
        patch("backend.extractor.trafilatura.extract_metadata", return_value=meta),
    ):
        article = extract_article("https://example.com/long")

    assert len(article.text) <= MAX_TEXT_CHARS + 30
    assert article.text.endswith("...[truncated]")


def test_agent_orchestrator_tool_message_uses_unwrapped_counts():
    from backend.agent_orchestrator import _parse_tool_payload, _tool_done_message

    wrapped = json.dumps(
        {
            "status": "ok",
            "result": json.dumps(
                {
                    "status": "ok",
                    "title": "Shopify Guide",
                    "char_count": 8015,
                }
            ),
        }
    )
    payload = _parse_tool_payload(wrapped)
    msg = _tool_done_message("extract_article_tool", payload)
    assert "8015" in msg
    assert "Shopify Guide" in msg
