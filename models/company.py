"""Data model for a company entity."""

import json
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Company:
    """Represents a discovered company with all extracted fields."""

    company_name: str
    website: Optional[str] = None
    email: Optional[str] = None
    description: Optional[str] = None
    contact_page: Optional[str] = None
    address: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    score: int = 0

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary (all fields, including None)."""
        return asdict(self)

    def to_clean_dict(self) -> dict:
        """Serialize omitting None values and empty lists (for clean JSON output)."""
        return {k: v for k, v in asdict(self).items() if v is not None and v != []}

    def to_json(self) -> str:
        """Serialize to a clean JSON string (None values omitted)."""
        return json.dumps(self.to_clean_dict(), ensure_ascii=False, indent=2)

    def is_valid(self) -> bool:
        """Return True if the company has at minimum a non-empty name."""
        return bool(self.company_name and self.company_name.strip())
