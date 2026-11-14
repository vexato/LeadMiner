from models.company import Company
from utils.deduplicator import deduplicate, normalize_text
from utils.validators import extract_domain

ADDRESS = "12 rue des Quais 33000 Bordeaux"
WEBSITE = "https://www.web.fr/contact"


def test_hostname_normalization_uses_a_single_prefix():
    assert extract_domain(WEBSITE) == "web.fr"
    assert extract_domain("https://WEB.fr:443/") == "web.fr"
    assert extract_domain("web.fr/") == "web.fr"
    assert extract_domain("https://ww.web.fr") == "ww.web.fr"


def test_matching_same_address_and_name_preserves_registry_conflict():
    official = Company("Salon Étoile SAS", address=ADDRESS, siret="11111111100010", siren="111111111")
    official.record_discovery("sirene")
    candidate = Company("Salon Etoile", address="12 rue des Quais, 33000 BORDEAUX", website=WEBSITE)
    candidate.record_discovery("catalog")
    [merged] = deduplicate([candidate, official])
    assert normalize_text("Salon Étoile") == "salon etoile"
    assert merged.siret == official.siret
    assert merged.website == WEBSITE
    assert {item.source for item in merged.observations} == {"sirene", "catalog"}


def test_protected_homonyms_and_branches():
    first = Company("Salon Étoile", address=ADDRESS, website=WEBSITE, siret="11111111100010")
    branch = Company("Salon Étoile", address=ADDRESS, website=WEBSITE, siret="11111111100028")
    ambiguous = Company("Salon Etoile", address=ADDRESS, website=WEBSITE)
    unknown = Company("Salon Étoile", website=WEBSITE, address="Bordeaux")
    records = deduplicate([first, branch, ambiguous, unknown])
    assert len(records) == 4
    assert any(row.identity_notes == ["ambiguous_siret"] for row in records)


def test_conflicting_domains_prevent_transitive_merge():
    a = Company("Salon Étoile", address=ADDRESS, website="https://web.fr")
    b = Company("Salon Étoile", address=ADDRESS)
    c = Company("Salon Étoile", address=ADDRESS, website="https://eb.fr")
    assert len(deduplicate([a, b, c])) == len(deduplicate([c, b, a])) == 3


def test_known_siret_deduplicates_and_retains_competing_address():
    first = Company("Salon Étoile", address=ADDRESS, siret="11111111100010")
    second = Company("Salon Étoile", address="14 rue des Quais 33000 Bordeaux", siret=first.siret)
    first.record_discovery("sirene")
    second.record_discovery("catalog")
    [match] = deduplicate([second, first])
    assert "conflicting_address" in match.identity_notes
    assert {obs.value for obs in match.observations if obs.field == "address"} == {first.address, second.address}
