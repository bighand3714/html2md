"""Error types and warning collection for html2md."""

from bs4 import Tag


class ConversionError(Exception):
    """Base exception for all conversion errors."""
    pass


class StrategyNotFoundError(ConversionError):
    """Raised when no site strategy matches the input."""
    pass


class CitationMappingError(ConversionError):
    """Raised when a citation reference cannot be mapped."""
    pass


class ImageExtractionError(ConversionError):
    """Raised when a base64 image cannot be extracted."""
    pass


class TableConversionError(ConversionError):
    """Raised when a table cannot be converted."""
    pass


class DownloadError(ConversionError):
    """Raised when a URL cannot be downloaded."""
    pass


class WarningCollector:
    """Collects non-fatal warnings during conversion.

    Used in lenient mode (default). In strict mode, warnings
    are escalated to exceptions.
    """

    def __init__(self, strict: bool = False):
        self.strict = strict
        self._warnings: list[str] = []

    def warn(self, message: str, element: Tag | None = None) -> None:
        """Record a warning, or raise if in strict mode."""
        if self.strict:
            el_info = f" (element: {element.name})" if element is not None else ""
            raise ConversionError(f"{message}{el_info}")
        el_info = f" [<{element.name}>]" if element is not None else ""
        self._warnings.append(f"{message}{el_info}")

    def has_warnings(self) -> bool:
        return len(self._warnings) > 0

    def flush(self) -> list[str]:
        """Return all warnings and clear the collector."""
        result = self._warnings.copy()
        self._warnings.clear()
        return result
