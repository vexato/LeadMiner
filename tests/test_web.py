import asyncio
from pathlib import Path

import aiohttp
import pytest
from aiohttp.resolver import ThreadedResolver

from config.settings import Settings
from core.pipeline import Pipeline
from core.qualification import WebAgencyProfile
from extractors.email_extractor import EmailExtractor
from extractors.text_extractor import TextExtractor
from models.company import Company
from scrapers.website_scraper import Page, Site, WebsiteScraper
from utils.public_http import FetchError, PublicResolver, public_url

HTML = (Path(__file__).parent / "fixtures" / "contact.html").read_text()
ORIGIN = "https://atelierdesquais.fr"


class Response:
    def __init__(self, status=200, body="", headers=None, content_type="text/html"):
        self.status, self.headers = status, headers or {}
        self.content_length = None
        self.content_type, self.charset = content_type, None
        self.content = self
        self.body = body

    async def iter_chunked(self, size):
        data = self.body.encode()
        for start in range(0, len(data), size):
            yield data[start:start + size]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class HTTP:
    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    async def get(self, url, *, allow_redirects):
        assert not allow_redirects
        self.urls.append(str(url))
        response = self.routes.get(str(url), Response(404))
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://127.0.0.1", "http://127.1", "http://2130706433",
    "http://0x7f.0.0.1", "http://169.254.169.254", "http://10.5.0.1",
    "http://224.0.0.1", "https://x.local", "https://host.example:8000",
    "https://name@host.example", "https://user:pass@host.example",
    "http://[::ffff:127.0.0.1]", "http://[fc00::1]", "http://[64:ff9b::7f00:1]",
    "https://host.example\\@another.example", "https://x.test\n@y.test",
])
def test_url_validation(url):
    with pytest.raises(FetchError):
        public_url(url)


def test_resolver_rejects_mixed_dns_replies(monkeypatch):
    async def run():
        async def mixed(self, host, port, family):
            return [{"host": "1.1.1.1"}, {"host": "192.168.100.1"}]

        monkeypatch.setattr(ThreadedResolver, "resolve", mixed)
        resolver = PublicResolver()
        with pytest.raises(OSError, match="non_public"):
            await resolver.resolve("mapped.example")
        await resolver.close()

    asyncio.run(run())


@pytest.mark.parametrize("target, failure", [
    ("http://169.254.169.254/latest/", "non_public_address"),
    ("https://another.example/", "redirect_outside_site"),
    ("http://atelierdesquais.fr/", "redirect_outside_site"),
])
def test_redirect_is_checked_before_following(target, failure):
    http = HTTP({ORIGIN + "/": Response(302, headers={"Location": target})})
    site = asyncio.run(WebsiteScraper(Settings()).scrape(ORIGIN + "/", http))
    assert http.urls == [ORIGIN + "/robots.txt", ORIGIN + "/"]
    assert site.issues == [(failure, ORIGIN + "/")]


def test_robots_body_limits_mime_and_timeouts():
    settings = Settings(website_max_bytes=75)
    for routes, code in (
        ({ORIGIN + "/robots.txt": Response(body="User-agent: *\nDisallow: /")}, "robots_disallowed"),
        ({ORIGIN + "/": Response(body="a" * 76)}, "body_too_large"),
        ({ORIGIN + "/": Response(content_type="application/pdf")}, "non_html_response"),
        ({ORIGIN + "/": Response(body="a", headers={"Content-Encoding": "gzip"})}, "unsupported_content_encoding"),
        ({ORIGIN + "/": TimeoutError()}, "request_timeout"),
        ({ORIGIN + "/": aiohttp.ClientConnectionError()}, "network_error"),
    ):
        site = asyncio.run(WebsiteScraper(settings).scrape(ORIGIN + "/", HTTP(routes)))
        assert site.issues == [(code, ORIGIN + "/")]


def test_robots_wildcard_restricts_discovered_contact_link():
    target = ORIGIN + "/notre-salon/nous-ecrire"
    http = HTTP({
        ORIGIN + "/": Response(body=HTML),
        ORIGIN + "/robots.txt": Response(body="User-agent: LeadMiner\nDisallow: /*/nous-ecrire$"),
        target: Response(body="<title>Contact</title>"),
    })
    site = asyncio.run(WebsiteScraper(Settings()).scrape(ORIGIN + "/", http))
    assert target not in http.urls
    assert ("robots_disallowed", target) in site.issues


def test_uses_link_before_fallback_and_rejects_duplicate_homepage():
    found = ORIGIN + "/notre-salon/nous-ecrire"
    http = HTTP({ORIGIN + "/": Response(body=HTML), found: Response(body="<title>Contact</title>"),
                 ORIGIN + "/contact": Response(body=HTML)})
    site = asyncio.run(WebsiteScraper(Settings()).scrape(ORIGIN + "/", http))
    assert http.urls[2] == found
    assert [page.url for page in site.linked_pages] == [found]
    assert ("duplicate_page_body", ORIGIN + "/contact") in site.issues
    assert len(http.urls) <= Settings().website_max_requests


def test_extractor_fixtures():
    assert EmailExtractor().extract_from_html(HTML) == ["bonjour@atelierdesquais.fr"]
    assert EmailExtractor().extract_from_html("bonjour [at] salon [dot] fr") == ["bonjour@salon.fr"]
    assert EmailExtractor().extract_from_html("congratulations greatdotcom info@example.org") == []
    assert TextExtractor().extract_description(HTML).startswith("Atelier de coiffure indépendant")
    assert len(TextExtractor(31).extract_description(HTML)) <= 31


@pytest.mark.parametrize("siret, status", [
    ("11111111100010", "official_confirmed"), ("11111111100028", "candidate_reachable"),
    (None, "candidate_reachable"),
])
def test_pipeline_attributes_contact_only_to_matched_establishment(siret, status):
    company = Company("Atelier des Quais", website=ORIGIN, siret=siret, activity_match="confirmed")
    Pipeline(Settings())._apply(company, Site(homepage=Page(ORIGIN, HTML)))
    assert company.website_status == status
    score = WebAgencyProfile().evaluate(company)
    if status == "official_confirmed":
        email = next(obs for obs in company.observations if obs.field == "email")
        assert email.url == ORIGIN
        assert company.email == email.value
        assert score["opportunity_score"] == 20
        assert score["reasons"][0]["url"] == ORIGIN
    else:
        assert all(obs.field != "email" for obs in company.observations)
        assert company.email is None
        assert score["opportunity_score"] is None


def test_siret_alone_does_not_attribute_a_generic_directory_page():
    company = Company("Atelier des Quais", website=ORIGIN, siret="11111111100010")
    directory = HTML.replace("<title>Atelier des Quais</title>", "<title>Annuaire régional</title>")
    Pipeline(Settings())._apply(company, Site(homepage=Page(ORIGIN, directory)))
    assert company.website_status == "candidate_reachable"
    assert company.email is None


def test_http_candidate_probes_https_first():
    candidate = "http://atelierdesquais.fr/"
    http = HTTP({ORIGIN + "/": Response(body=HTML)})
    site = asyncio.run(WebsiteScraper(Settings()).scrape(candidate, http))
    assert site.homepage.url == ORIGIN + "/"
    assert site.https_status == "available"
    assert candidate not in http.urls
