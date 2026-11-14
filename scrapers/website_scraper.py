"""Collect bounded HTML evidence from a public site."""

import asyncio
import re
from dataclasses import dataclass, field

import aiohttp
from bs4 import BeautifulSoup
from protego import Protego

from config.settings import Settings
from utils.deduplicator import normalize_text
from utils.public_http import FetchError, bounded_body, public_url
from utils.validators import extract_domain

_CONTACT = re.compile(r"\b(?:contact|contacter|coordonnees|mentions legales|impressum|legal|about|a propos)\b")
_DENIAL = re.compile(r"captcha|access denied|just a moment|acc[eè]s refus[eé]", re.I)
_NOT_FOUND = re.compile(r"\b404\b|page introuvable|page not found", re.I)
_REDIRECTS = {301, 302, 303, 307, 308}


@dataclass(frozen=True)
class Page:
    url: str
    html: str


@dataclass
class Site:
    homepage: Page | None = None
    linked_pages: list[Page] = field(default_factory=list)
    issues: list[tuple[str, str]] = field(default_factory=list)
    https_status: str = "unknown"


class WebsiteScraper:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def scrape(self, url: str, session: aiohttp.ClientSession) -> Site:
        site = Site()
        remaining = self.settings.website_max_requests
        policies: dict[str, Protego] = {}

        async def request(target):
            nonlocal remaining
            if remaining <= 0:
                raise FetchError("request_budget_exhausted")
            remaining -= 1
            return await session.get(target, allow_redirects=False)

        async def check_robots(target):
            origin = str(target.origin())
            if origin not in policies:
                async with await request(target.origin() / "robots.txt") as response:
                    if response.status == 200:
                        body = await bounded_body(response, 128_000)
                        parser = Protego.parse(body.decode("utf-8", errors="replace"))
                    elif response.status in {404, 410}:
                        parser = Protego.parse("")
                    else:
                        raise FetchError(f"robots_http_{response.status}")
                policies[origin] = parser
            if not policies[origin].can_fetch(str(target), "LeadMiner"):
                raise FetchError("robots_disallowed")

        async def fetch(raw: str) -> Page:
            target = public_url(raw)
            for _ in range(4):
                await check_robots(target)
                async with await request(target) as response:
                    if response.status in _REDIRECTS:
                        location = response.headers.get("Location")
                        if not location:
                            raise FetchError("redirect_without_location")
                        # Validate raw bytes too, before URL parsers can trim or escape them.
                        if re.search(r"[\x00-\x1f\x7f\\]", location):
                            raise FetchError("invalid_redirect")
                        redirect = public_url(_join(target, location))
                        if (extract_domain(str(redirect)) != extract_domain(str(target))
                                or target.scheme == "https" and redirect.scheme != "https"):
                            raise FetchError("redirect_outside_site")
                        target = redirect
                        continue
                    if response.status != 200:
                        raise FetchError(f"http_{response.status}")
                    if response.content_type not in {"text/html", "application/xhtml+xml"}:
                        raise FetchError("non_html_response")
                    body = await bounded_body(response, self.settings.website_max_bytes)
                    try:
                        html = body.decode(response.charset or "utf-8", errors="replace")
                    except LookupError as exc:
                        raise FetchError("unknown_charset") from exc
                    title = BeautifulSoup(html, "lxml").title
                    if title and _DENIAL.search(title.get_text()):
                        raise FetchError("site_access_restricted")
                    if title and _NOT_FOUND.search(title.get_text()):
                        raise FetchError("soft_404")
                    return Page(str(target), html)
            raise FetchError("too_many_redirects")

        async def collect(target: str) -> Page | None:
            try:
                return await fetch(target)
            except FetchError as exc:
                code = str(exc)
            except aiohttp.ClientSSLError:
                code = "tls_error"
            except TimeoutError:
                code = "request_timeout"
            except aiohttp.ClientError:
                code = "network_error"
            site.issues.append((code, target))
            return None

        try:
            async with asyncio.timeout(self.settings.website_budget):
                candidate = public_url(url)
                if candidate.scheme == "http":
                    secure_url = str(candidate.with_scheme("https"))
                    site.homepage = await collect(secure_url)
                    if site.homepage is None:
                        failure, _ = site.issues[-1]
                        # Respect restrictions or resource limits encountered on HTTPS.
                        if failure not in {"tls_error", "network_error", "request_timeout",
                                           "http_404", "http_410"}:
                            return site
                        site.https_status = "probe_failed"
                if site.homepage is None:
                    site.homepage = await collect(url)
                if site.homepage is None:
                    return site
                if site.homepage.url.startswith("https://"):
                    site.https_status = "available"
                links = self._contact_links(site.homepage)
                known_html = {site.homepage.html}
                for candidate in links[:3]:
                    found = await collect(candidate)
                    if found and found.html not in known_html and found.url != site.homepage.url:
                        site.linked_pages.append(found)
                        known_html.add(found.html)
                    elif found:
                        site.issues.append(("duplicate_page_body", candidate))
        except TimeoutError:
            site.issues.append(("site_budget_timeout", url))
        return site

    def _contact_links(self, page: Page) -> list[str]:
        root = public_url(page.url)
        soup = BeautifulSoup(page.html, "lxml")
        links = {}
        for tag in soup.find_all("a", href=True):
            href = str(tag["href"])
            if not _CONTACT.search(normalize_text(tag.get_text(" ", strip=True) + " " + href)):
                continue
            try:
                target = public_url(_join(root, href))
            except FetchError:
                continue
            if extract_domain(str(target)) == extract_domain(page.url) and target != root:
                links[str(target)] = None
        for path in self.settings.contact_paths:
            if path.startswith("/") and not path.startswith("//"):
                candidate = _join(root, path)
                if candidate != page.url:
                    links.setdefault(candidate, None)
        return list(links)


def _join(base, path: str) -> str:
    from urllib.parse import urljoin

    try:
        return urljoin(str(base), path)
    except ValueError as exc:
        raise FetchError("invalid_link") from exc
