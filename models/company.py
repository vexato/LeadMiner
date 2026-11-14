"""An establishment as seen in a search, with field-level observations."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class Observation:
    field: str
    value: str | None
    source: str
    method: str
    status: str = "observed"
    confidence: str = "low"
    url: str | None = None
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Company:
    company_name: str
    website: str | None = None
    email: str | None = None
    description: str | None = None
    contact_page: str | None = None
    address: str | None = None
    sources: list[str] = field(default_factory=list)
    score: int = 0
    siren: str | None = None
    siret: str | None = None
    legal_name: str | None = None
    trade_name: str | None = None
    activity_code: str | None = None
    commune_code: str | None = None
    postal_code: str | None = None
    activity_match: str = "unknown"
    website_status: str = "unknown"
    enrichment_status: str = "not_started"
    observations: list[Observation] = field(default_factory=list)
    identity_notes: list[str] = field(default_factory=list)
    qualification: dict = field(default_factory=dict)

    def observe(self, field: str, value: str | None, source: str, method: str, **evidence) -> None:
        self.observations.append(Observation(field, value, source, method, **evidence))

    def record_discovery(self, source: str, url: str | None = None) -> None:
        if source not in self.sources:
            self.sources.append(source)
        if self.website and self.website_status == "unknown":
            self.website_status = "candidate"
        fields = (
            "company_name", "website", "email", "address", "description", "contact_page",
            "siren", "siret", "legal_name", "trade_name", "activity_code", "commune_code",
            "postal_code",
        )
        recorded = {(obs.field, obs.source) for obs in self.observations}
        for field_name in fields:
            if (value := getattr(self, field_name)) and (field_name, source) not in recorded:
                if source == "sirene":
                    self.observe(field_name, value, source, "public_registry",
                                 status="registry_reported", confidence="high", url=url)
                else:
                    self.observe(field_name, value, source, "source_listing", url=url)

    @classmethod
    def from_dict(cls, payload: dict) -> "Company":
        data = {**payload, "observations": [Observation(**row) for row in payload.get("observations", [])]}
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_clean_dict(self) -> dict:
        return {key: value for key, value in self.to_dict().items() if value not in (None, [], {})}

    def to_json(self) -> str:
        return json.dumps(self.to_clean_dict(), ensure_ascii=False, indent=2)

    def is_valid(self) -> bool:
        return bool(self.company_name and self.company_name.strip())
