#!/usr/bin/env python3
"""Use Crawl4AI to crawl the three YAFCO futures-rule pages.

The crawler stores the rendered HTML, cleaned HTML, Markdown, and a compact
JSON metadata file for each page under ``crawl4ai_outputs/`` by default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parent

# Crawl4AI initializes its database during import. Keep its state in this
# project because the desktop environment may not permit writing to $HOME.
os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", str(PROJECT_ROOT))

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig


@dataclass(frozen=True)
class Page:
    page_id: int
    title: str
    url: str


PAGES = (
    Page(
        page_id=804,
        title="交易所期货限仓",
        url="https://www.yafco.com/jiaoyidating_show.html?id=804",
    ),
    Page(
        page_id=805,
        title="交易所期权限仓",
        url="https://www.yafco.com/jiaoyidating_show.html?id=805",
    ),
    Page(
        page_id=970,
        title="期货开仓总量限制",
        url="https://www.yafco.com/jiaoyidating_show.html?id=970",
    ),
)


def safe_filename(value: str) -> str:
    """Make a readable filename without path separators or control chars."""

    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip()
    return value or "page"


def write_text(path: Path, content: str | None) -> None:
    path.write_text(content or "", encoding="utf-8")


def extract_content_images(html: str | None, base_url: str) -> list[dict[str, Any]]:
    """Return images in the article body, excluding site-wide decorations."""

    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.select_one(".ya-con") or soup.select_one("article")
    if container is None:
        return []

    images = []
    for image in container.select("img[src]"):
        images.append(
            {
                "url": urljoin(base_url, image["src"]),
                "alt": image.get("alt", ""),
                "width": image.get("width"),
                "height": image.get("height"),
            }
        )
    return images


def result_metadata(page: Page, result: Any) -> dict[str, Any]:
    """Extract serializable diagnostics from a Crawl4AI result."""

    links = getattr(result, "links", {}) or {}
    media = getattr(result, "media", {}) or {}
    final_url = getattr(result, "url", None) or page.url
    content_images = extract_content_images(
        getattr(result, "cleaned_html", None), final_url
    )
    return {
        "page_id": page.page_id,
        "title": page.title,
        "requested_url": page.url,
        "final_url": final_url,
        "success": bool(getattr(result, "success", False)),
        "status_code": getattr(result, "status_code", None),
        "error_message": getattr(result, "error_message", None),
        "markdown_chars": len(getattr(result, "markdown", None) or ""),
        "fit_markdown_chars": len(getattr(result, "fit_markdown", None) or ""),
        "html_chars": len(getattr(result, "html", None) or ""),
        "cleaned_html_chars": len(getattr(result, "cleaned_html", None) or ""),
        "internal_link_count": len(links.get("internal", []) or []),
        "external_link_count": len(links.get("external", []) or []),
        "image_count": len(media.get("images", []) or []),
        "content_images": content_images,
    }


def build_browser_config(headed: bool) -> BrowserConfig:
    return BrowserConfig(
        browser_type="chromium",
        headless=not headed,
        enable_stealth=True,
        viewport_width=1440,
        viewport_height=900,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        ),
    )


def build_run_config(screenshot: bool) -> CrawlerRunConfig:
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=1,
        target_elements=[".ya-content"],
        wait_until="domcontentloaded",
        # The article title and its body image are injected by
        # /yingyeting/detail after the initial document has loaded.
        wait_for=".ya-con img",
        wait_for_timeout=30_000,
        page_timeout=90_000,
        delay_before_return_html=1.0,
        scan_full_page=True,
        scroll_delay=0.2,
        max_scroll_steps=30,
        process_iframes=True,
        screenshot=screenshot,
    )


async def crawl_pages(output_dir: Path, headed: bool, screenshot: bool) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_config = build_run_config(screenshot)
    summary: list[dict[str, Any]] = []

    async with AsyncWebCrawler(config=build_browser_config(headed)) as crawler:
        for page in PAGES:
            print(f"[crawl] {page.page_id} {page.title}: {page.url}", flush=True)
            result = await crawler.arun(page.url, config=run_config)
            metadata = result_metadata(page, result)
            stem = f"{page.page_id}_{safe_filename(page.title)}"

            write_text(output_dir / f"{stem}.md", getattr(result, "markdown", None))
            write_text(output_dir / f"{stem}.html", getattr(result, "html", None))
            write_text(
                output_dir / f"{stem}.cleaned.html",
                getattr(result, "cleaned_html", None),
            )
            (output_dir / f"{stem}.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary.append(metadata)
            print(
                f"[done] success={metadata['success']} "
                f"status={metadata['status_code']} "
                f"markdown_chars={metadata['markdown_chars']}",
                flush=True,
            )

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "crawl4ai_outputs",
        help="Directory for Crawl4AI output files.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Use a visible Chromium window; useful when the headless shell is unavailable.",
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        help="Ask Crawl4AI to capture a screenshot for each page.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(crawl_pages(args.output_dir, args.headed, args.screenshot))
    failed = [item for item in summary if not item["success"]]
    if failed:
        raise SystemExit(f"{len(failed)} page(s) failed; see {args.output_dir}/summary.json")


if __name__ == "__main__":
    main()
