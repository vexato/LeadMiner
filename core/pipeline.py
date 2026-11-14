"""Enrich candidate websites and record exactly where fields came from."""

import asyncio
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from time import perf_counter

from bs4 import BeautifulSoup

from config.settings import Settings
from extractors.email_extractor import EmailExtractor
from extractors.text_extractor import TextExtractor
from models.company import Company
from scrapers.website_scraper import Site, WebsiteScraper
from utils.deduplicator import normalize_text
from utils.helpers import normalize_url
from utils.logger import setup_logger
from utils.public_http import FetchError, public_session, public_url
from utils.validators import extract_domain

logger = setup_logger(__name__)
_SIRET = re.compile(r"\bsiret\b\s*(?:n[°º.]?\s*)?[:\-]?\s*((?:\d[ .\u00a0\u202f]*){13}\d)(?!\d)", re.I)
_BOOKING = re.compile(r"r[eé]server|rendez.vous|book (?:now|online)", re.I)
Checkpoint = Callable[[int, Company], Awaitable[None]]


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.website_scraper = WebsiteScraper(settings)
        self.text_extractor = TextExtractor(settings.max_description_length)

    async def enrich_all(
        self, companies: list[Company], *, finished: set[int] | None = None,
        checkpoint: Checkpoint | None = None, timings: list[float] | None = None,
    ) -> list[Company]:
        if not companies:
            return companies
        def target(company):
            return str(public_url(normalize_url(company.website))) if company.website else None

        def cache_key(company):
            try:
                return target(company)
            except FetchError:
                return None

        pending = [(idx, c) for idx, c in enumerate(companies) if idx not in (finished or ())]
        remaining = iter(pending)
        uses = Counter(cache_key(company) for _, company in pending)
        in_flight: dict[str, asyncio.Task[Site]] = {}
        limit = self.settings.max_concurrent_website_scrapers
        async with public_session(self.settings.website_timeout, limit=limit) as session:
            async def worker():
                for idx, company in remaining:
                    started = perf_counter()
                    try:
                        url = target(company)
                    except FetchError:
                        company.enrichment_status = "invalid_url"
                        company.observe("website", company.website, "website", "url_validation",
                                        status="rejected")
                        company.website_status = "invalid_candidate"
                    else:
                        if url:
                            if url not in in_flight:
                                in_flight[url] = asyncio.create_task(self.website_scraper.scrape(url, session))
                            site = await asyncio.shield(in_flight[url])
                            uses[url] -= 1
                            if not uses[url]:
                                del in_flight[url]
                            self._apply(company, site)
                        else:
                            company.enrichment_status = "no_candidate"
                    if timings is not None:
                        timings.append(perf_counter() - started)
                    if checkpoint:
                        await checkpoint(idx, company)

            try:
                async with asyncio.TaskGroup() as workers:
                    for _ in range(min(limit, len(companies))):
                        workers.create_task(worker())
            finally:
                for task in in_flight.values():
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*in_flight.values(), return_exceptions=True)
        return companies

    def _apply(self, company: Company, site: Site) -> None:
        for code, url in site.issues:
            company.observe("web_fetch", code, "website", "http", status="failed", url=url)
        home = site.homepage
        if home is None:
            company.enrichment_status = "failed"
            company.website_status = "candidate_unreachable"
            logger.warning("Website enrichment failed (%s)", site.issues[0][0] if site.issues else "no_response")
            return

        company.enrichment_status = "partial" if any(
            code not in {"http_404", "http_410", "duplicate_page_body"} for code, _ in site.issues
        ) else "completed"
        pages = [*site.linked_pages, home]
        siret_matches = set()
        for page in pages:
            text = BeautifulSoup(page.html, "lxml").get_text(" ", strip=True)
            for number in sorted({re.sub(r"\D", "", match) for match in _SIRET.findall(text)}):
                siret_matches.add(number)
                company.observe("website_published_siret", number, "website", "html",
                                status="observed", url=page.url)
        soup = BeautifulSoup(home.html, "lxml")
        heading = " ".join(normalize_text(tag.get_text(" ", strip=True))
                          for tag in soup.find_all(["title", "h1"]))
        name_matches = any(
            f" {name} " in f" {heading} " for value in (company.company_name, company.trade_name, company.legal_name)
            if value and len(name := normalize_text(value)) >= 4
        )
        official = bool(company.siret and siret_matches == {company.siret} and name_matches)
        company.website_status = "official_confirmed" if official else "candidate_reachable"
        company.observe("website", home.url, "website", "siret_match" if official else "http",
                        status="verified_identity" if official else "reachable",
                        confidence="high" if official else "low", url=home.url)
        if company.siret and siret_matches - {company.siret}:
            company.identity_notes.append("website_siret_conflict")

        signals = {
            "https": "available" if home.url.startswith("https://") else site.https_status,
            "viewport": "present" if soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) else "missing",
        }
        generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
        if generator and generator.get("content"):
            signals["generator"] = str(generator["content"])[:100]
        for page in pages:
            for anchor in BeautifulSoup(page.html, "lxml").find_all("a", href=True):
                if _BOOKING.search(anchor.get_text(" ", strip=True)):
                    href = str(anchor["href"])
                    if href and href != "#" and not href.lower().startswith(("javascript:", "mailto:", "tel:")):
                        company.observe("booking", "link_detected", "website", "html",
                                        status="checked", url=page.url)
                        break
            else:
                continue
            break
        for field, value in signals.items():
            company.observe(field, value, "website", "html" if field != "https" else "http",
                            status="checked", url=home.url)

        # A site's data stays evidence about that site until its identity is corroborated.
        status = "observed" if official else "unattributed"
        evidence = {"status": status, "confidence": "medium" if official else "low"}
        if site.linked_pages:
            page = site.linked_pages[0]
            company.observe("contact_page", page.url, "website", "contact_link_or_path", url=page.url, **evidence)
            if official and not company.contact_page:
                company.contact_page = page.url
        if official:
            for page in pages:
                emails = EmailExtractor().extract_from_html(page.html)
                hostname = extract_domain(home.url)
                email = next((address for address in emails
                              if extract_domain(address.rsplit("@", 1)[-1]) == hostname), None)
                if email:
                    company.observe("email", email, "website", "html_domain_match", url=page.url, **evidence)
                    if not company.email:
                        company.email = email
                    break
        if description := self.text_extractor.extract_description(home.html):
            company.observe("description", description, "website", "html_extraction", url=home.url, **evidence)
            if official and not company.description:
                company.description = description
