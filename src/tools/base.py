import datetime
from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def description(self) -> str:
        pass


class CalendarTool(BaseTool):
    @abstractmethod
    def list_events(
        self, start_time: datetime.datetime, end_time: datetime.datetime
    ) -> list[dict[str, Any]]:
        """List events in a given time range."""
        pass

    @abstractmethod
    def create_event(
        self,
        summary: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new event."""
        pass


class NotesTool(BaseTool):
    @abstractmethod
    def create_page(self, title: str, content: str) -> dict[str, Any]:
        """Create a new page or document."""
        pass

    @abstractmethod
    def append_content(self, page_id: str, content: str) -> dict[str, Any]:
        """Append content to an existing page."""
        pass
