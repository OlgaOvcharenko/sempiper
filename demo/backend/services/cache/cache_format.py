"""Cache format types."""

from enum import Enum


class CacheFormat(str, Enum):
    """Supported cache storage formats."""

    JSON = "json"
    SVG = "svg"
    TEXT = "txt"
    BINARY = "bin"
