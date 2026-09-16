from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import Settings
from .url_utils import validate_fetch_host


@dataclass(frozen=True)
class PageProfile:
    key: str
    target_elements: tuple[str, ...]
    wait_for: str
    image_selector: str
    title_selector: str


YAFCO_PROFILE = PageProfile(
    key="yafco_image",
    target_elements=(".ya-content",),
    wait_for=".ya-con img",
    image_selector=".ya-con img[src]",
    title_selector=".ya-content-tit h3",
)


@dataclass(frozen=True)
class ImageCandidateData:
    source_url: str
    resolved_url: str
    ordinal: int
    alt: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class CrawlSnapshot:
    requested_url: str
    final_url: str
    title: str
    success: bool
    status_code: int | None
    error_message: str
    candidates: tuple[ImageCandidateData, ...]
    metadata: dict[str, Any]


class CrawlFailure(RuntimeError):
    def __init__(self, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.metadata = metadata or {}


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def extract_content_images(html: str | None, base_url: str, profile: PageProfile = YAFCO_PROFILE) -> list[ImageCandidateData]:
    soup = BeautifulSoup(html or "", "html.parser")
    images = soup.select(profile.image_selector)
    result: list[ImageCandidateData] = []
    for image in images:
        source_url = str(image.get("src", "")).strip()
        if not source_url:
            continue
        result.append(
            ImageCandidateData(
                source_url=source_url,
                resolved_url=urljoin(base_url, source_url),
                ordinal=len(result),
                alt=str(image.get("alt", "")),
                width=_safe_int(image.get("width")),
                height=_safe_int(image.get("height")),
            )
        )
    return result


def build_browser_config(headed: bool = False):
    from crawl4ai import BrowserConfig

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


def build_run_config(profile: PageProfile, page_timeout_ms: int):
    from crawl4ai import CacheMode, CrawlerRunConfig

    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        word_count_threshold=1,
        target_elements=list(profile.target_elements),
        wait_until="domcontentloaded",
        wait_for=profile.wait_for,
        wait_for_timeout=30_000,
        page_timeout=page_timeout_ms,
        delay_before_return_html=1.0,
        scan_full_page=True,
        scroll_delay=0.2,
        max_scroll_steps=30,
        process_iframes=True,
        screenshot=False,
    )


def _title_from_html(html: str | None, profile: PageProfile) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.select_one(profile.title_selector) or soup.select_one("title")
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True) if node else "").strip()


class Crawl4AIAdapter:
    """Adapter around one reusable Crawl4AI browser session."""

    def __init__(self, settings: Settings, profile: PageProfile = YAFCO_PROFILE, headed: bool = False):
        self.settings = settings
        self.profile = profile
        self.headed = headed
        self._crawler = None
        self._run_config = None
        self._previous_base_directory: str | None = None

    async def __aenter__(self) -> "Crawl4AIAdapter":
        crawl_dir = self.settings.resolved_data_dir / ".crawl4ai"
        crawl_dir.mkdir(parents=True, exist_ok=True)
        self._previous_base_directory = os.environ.get("CRAWL4_AI_BASE_DIRECTORY")
        os.environ["CRAWL4_AI_BASE_DIRECTORY"] = str(crawl_dir)
        try:
            from crawl4ai import AsyncWebCrawler

            self._crawler = AsyncWebCrawler(config=build_browser_config(self.headed))
            await self._crawler.__aenter__()
            self._run_config = build_run_config(self.profile, self.settings.page_timeout_ms)
            return self
        except Exception as error:
            if self._crawler is not None:
                try:
                    await self._crawler.__aexit__(type(error), error, error.__traceback__)
                finally:
                    self._crawler = None
                    self._run_config = None
            self._restore_environment()
            raise

    def _restore_environment(self) -> None:
        if self._previous_base_directory is None:
            os.environ.pop("CRAWL4_AI_BASE_DIRECTORY", None)
        else:
            os.environ["CRAWL4_AI_BASE_DIRECTORY"] = self._previous_base_directory
        self._previous_base_directory = None

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._crawler is not None:
            try:
                await self._crawler.__aexit__(exc_type, exc, traceback)
            finally:
                self._crawler = None
                self._run_config = None
                self._restore_environment()
        else:
            self._run_config = None
            self._restore_environment()

    async def crawl(self, url: str) -> CrawlSnapshot:
        validate_fetch_host(url, self.settings.allow_private_hosts)
        if self._crawler is None or self._run_config is None:
            raise RuntimeError("Crawl4AI adapter must be used inside an async context")
        try:
            result = await self._crawler.arun(url, config=self._run_config)
        except Exception as error:
            raise CrawlFailure(str(error)) from error

        final_url = getattr(result, "url", None) or url
        html = getattr(result, "cleaned_html", None) or getattr(result, "html", None)
        candidates = extract_content_images(html, final_url, self.profile)
        title = _title_from_html(html, self.profile)
        links = getattr(result, "links", {}) or {}
        media = getattr(result, "media", {}) or {}
        metadata = {
            "requested_url": url,
            "final_url": final_url,
            "title": title,
            "success": bool(getattr(result, "success", False)),
            "status_code": getattr(result, "status_code", None),
            "error_message": getattr(result, "error_message", "") or "",
            "markdown_chars": len(getattr(result, "markdown", None) or ""),
            "fit_markdown_chars": len(getattr(result, "fit_markdown", None) or ""),
            "html_chars": len(getattr(result, "html", None) or ""),
            "cleaned_html_chars": len(getattr(result, "cleaned_html", None) or ""),
            "internal_link_count": len(links.get("internal", []) or []),
            "external_link_count": len(links.get("external", []) or []),
            "image_count": len(media.get("images", []) or []),
            "content_images": [candidate.__dict__ for candidate in candidates],
        }
        if not metadata["success"]:
            message = metadata["error_message"] or "page crawl failed"
            raise CrawlFailure(message, metadata)
        return CrawlSnapshot(
            requested_url=url,
            final_url=final_url,
            title=title,
            success=True,
            status_code=metadata["status_code"],
            error_message=metadata["error_message"],
            candidates=tuple(candidates),
            metadata=metadata,
        )
