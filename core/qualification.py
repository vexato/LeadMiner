"""Evidence-based qualification for an agency offering website services."""

from dataclasses import dataclass

from models.company import Company


@dataclass(frozen=True)
class WebAgencyProfile:
    missing_viewport_points: int = 20

    def evaluate(self, company: Company) -> dict:
        registry_fields = {
            obs.field for obs in company.observations if obs.status == "registry_reported"
        }
        quality = sum(weight for field, weight in (
            ("siret", 40), ("address", 25), ("activity_code", 15),
        ) if field in registry_fields)
        official = company.website_status == "official_confirmed"
        if official:
            quality += 10
        if official and company.email:
            quality += 10
        evidence = []
        points = 0
        if official and company.activity_match == "confirmed":
            for observation in company.observations:
                if observation.status != "checked":
                    continue
                if observation.field == "viewport" and observation.value == "missing":
                    points += self.missing_viewport_points
                    evidence.append({"signal": "viewport_tag_missing", "url": observation.url})
            applicability = "evaluated"
        else:
            applicability = "insufficient_evidence"
        return {
            "profile": "web_agency",
            "data_quality": quality,
            "opportunity_score": min(100, points) if applicability == "evaluated" else None,
            "assessment": applicability,
            "confidence": "medium" if applicability == "evaluated" else "low",
            "reasons": evidence,
        }
