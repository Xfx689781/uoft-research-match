"""Parser registry. Each department in departments.yaml names a parser here.

A parser implements:
    start_urls(dept) -> list[str]
    parse(html, url, dept) -> ParseResult
`next_urls` lets paginated directories (or profile pages) be followed by the scraper CLI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..config import Department
from ..models import FacultyRecord


@dataclass
class ParseResult:
    records: list[FacultyRecord] = field(default_factory=list)
    next_urls: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # human-readable reasons, for the summary


class DirectoryParser(Protocol):
    def start_urls(self, dept: Department) -> list[str]: ...
    def parse(self, html: str, url: str, dept: Department) -> ParseResult: ...


def get_parser(name: str) -> DirectoryParser:
    from .cs_squarespace import CSSquarespaceParser

    registry: dict[str, DirectoryParser] = {
        "cs_squarespace": CSSquarespaceParser(),
        # "artsci_drupal": Math + Stats; written once we have real HTML to build it against.
    }
    if name not in registry:
        raise NotImplementedError(f"No parser registered for {name!r}")
    return registry[name]
