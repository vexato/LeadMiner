"""Conservative establishment matching. Ambiguity is retained for review."""

import re
import unicodedata
from collections import defaultdict
from dataclasses import replace
from difflib import SequenceMatcher

from models.company import Company
from utils.validators import extract_domain

_LEGAL_SUFFIX = re.compile(r" (?:sarl|sasu|sas|sa|eurl|sci|snc|ltd|llc|inc|gmbh|bv|nv|spa|oy)$")
_FULL_ADDRESS = re.compile(r"^\d+\s+.+\b\d{5}\s+[^\d]+$")
_FIELDS = (
    "company_name", "address", "website", "email", "description", "contact_page",
    "siren", "legal_name", "trade_name", "activity_code", "commune_code", "postal_code",
)


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold().replace("œ", "oe"))
    return " ".join(re.sub(r"[^\w]+|_", " ", "".join(
        ch for ch in text if not unicodedata.combining(ch)
    )).split())


def _address(company: Company) -> str | None:
    value = normalize_text(company.address or "")
    return value if _FULL_ADDRESS.fullmatch(value) else None


def _names(company: Company) -> set[str]:
    return {
        name for value in (company.company_name, company.legal_name, company.trade_name)
        if value and (name := _LEGAL_SUFFIX.sub("", normalize_text(value)))
    }


def _match(a: Company, b: Company) -> bool:
    if a.siren and b.siren and a.siren != b.siren:
        return False
    domains = [extract_domain(c.website) for c in (a, b)]
    if all(domains) and domains[0] != domains[1]:
        return False
    names_a, names_b = _names(a), _names(b)
    if names_a & names_b:
        return True
    return bool(domains[0] and domains[0] == domains[1] and any(
        min(len(x), len(y)) >= 8 and SequenceMatcher(None, x, y, autojunk=False).ratio() >= 0.94
        for x in sorted(names_a) for y in sorted(names_b)
    ))


def _merge(group: list[Company]) -> Company:
    ordered = sorted(group, key=lambda c: ("sirene" not in c.sources, not c.siret))
    first = ordered[0]
    notes = {note for c in group for note in c.identity_notes}
    values = {}
    for field in _FIELDS:
        candidates = [getattr(c, field) for c in ordered if getattr(c, field)]
        if candidates:
            values[field] = candidates[0]
            key = extract_domain if field == "website" else normalize_text
            if len({key(value) for value in candidates}) > 1:
                notes.add(f"conflicting_{field}")
    observations = list(dict.fromkeys(obs for c in group for obs in c.observations))
    return replace(first, **values, observations=observations,
                   sources=sorted({source for c in group for source in c.sources}),
                   identity_notes=sorted(notes))


def deduplicate(companies: list[Company]) -> list[Company]:
    groups: list[list[Company]] = []
    legal: dict[str, int] = {}
    weak: dict[str, list[Company]] = defaultdict(list)
    by_address: dict[str, set[int]] = defaultdict(set)

    for company in companies:
        address = _address(company)
        if company.siret:
            if company.siret not in legal:
                legal[company.siret] = len(groups)
                groups.append([])
            idx = legal[company.siret]
            groups[idx].append(company)
            if address:
                by_address[address].add(idx)
        elif address:
            weak[address].append(company)
        else:
            groups.append([company])

    for address, bucket in weak.items():
        unassigned: list[Company] = []
        # Compare with original SIRET-bearing observations, never with transitive aliases.
        originals = {idx: tuple(groups[idx]) for idx in by_address[address]}
        assignments = defaultdict(list)
        for company in bucket:
            matches = [idx for idx, rows in originals.items() if any(
                _address(row) == address and _match(company, row) for row in rows
            )]
            if len(matches) == 1:
                assignments[matches[0]].append(company)
            elif matches:
                groups.append([replace(company, identity_notes=company.identity_notes + ["ambiguous_siret"])])
            else:
                unassigned.append(company)
        for idx, rows in assignments.items():
            if all(_match(a, b) for i, a in enumerate(rows) for b in rows[i + 1:]):
                groups[idx].extend(rows)
            else:
                groups.extend([replace(row, identity_notes=row.identity_notes + ["conflicting_candidates"])]
                              for row in rows)

        # Only merge complete cliques. A-B-C chains with conflicting A and C stay separate.
        neighbors = [{i} for i in range(len(unassigned))]
        for i, a in enumerate(unassigned):
            for j in range(i + 1, len(unassigned)):
                if _match(a, unassigned[j]):
                    neighbors[i].add(j)
                    neighbors[j].add(i)
        for i, peers in enumerate(neighbors):
            if all(neighbors[j] == peers for j in peers):
                if i == min(peers):
                    groups.append([unassigned[j] for j in sorted(peers)])
            else:
                row = unassigned[i]
                groups.append([replace(row, identity_notes=row.identity_notes + ["ambiguous_match"])])

    return [_merge(group) for group in groups]
