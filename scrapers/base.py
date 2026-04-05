"""Common interface for all company data sources."""

from abc import ABC, abstractmethod

from models.company import Company


class BaseSource(ABC):
    """
    Every data source must implement this interface.

    This makes sources interchangeable: the orchestrator only calls
    ``search()`` and never cares which backend it is talking to.

    To add a new source:
      1. Create ``scrapers/my_source.py``
      2. Subclass ``BaseSource``
      3. Implement ``search()``
      4. Register in ``scrapers/registry.py``
    """

    #: Short identifier used in CLI --source and log messages
    name: str = "unnamed"

    @abstractmethod
    async def search(self, query: str, location: str, limit: int) -> list[Company]:
        """
        Discover companies and return basic Company objects.

        The pipeline will later enrich each company (email, description, …)
        by visiting its website.  This method only needs to return:
          - company_name  (required)
          - website       (if available in the source)
          - address       (if available in the source)

        Args:
            query:    Domain or activity type (e.g. "web development").
            location: City or region (e.g. "Bordeaux").
            limit:    Maximum number of results to return.

        Returns:
            List of Company objects — never raises, returns [] on error.
        """
        ...
