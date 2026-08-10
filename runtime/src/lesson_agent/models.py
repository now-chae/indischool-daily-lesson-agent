from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Lesson:
    period: int
    subject: str
    topic: str
    pages: str | None = None
    unit_name: str | None = None


@dataclass(frozen=True, slots=True)
class Resource:
    title: str
    url: str
    subject: str
    snippet: str
    rank: int
    material_type: str | None = None


@dataclass(frozen=True, slots=True)
class SearchLesson:
    subject: str
    topic: str
    periods: tuple[int, ...]
    pages: str | None = None
    unit_name: str | None = None
