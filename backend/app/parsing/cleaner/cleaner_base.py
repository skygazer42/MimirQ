"""Abstract interface for document cleaner implementations."""

from abc import ABC, abstractmethod


class BaseCleaner(ABC):
    """Interface for clean chunk content."""

    @abstractmethod
    def clean(self, content: str) -> str:
        """Clean the content.

        Args:
            content: The content to clean

        Returns:
            Cleaned content string
        """
        raise NotImplementedError
