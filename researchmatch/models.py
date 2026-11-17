"""Common output schema shared by every department parser."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class FacultyRecord:
    name: str
    title: str                       # rank exactly as printed, e.g. "Associate Professor, Teaching Stream"
    rank: str                        # normalized, see ranks.py
    appointment_type: str            # research_stream | teaching_stream | emeritus | cross_appointed | ...
    department_id: str
    department_name: str
    source_url: str                  # official page this record was read from
    is_emeritus: bool = False
    home_unit: str | None = None     # e.g. "Psychology" for cross-appointed faculty
    email: str | None = None         # only when printed on the page; never constructed
    profile_url: str | None = None   # official departmental profile page, if one exists
    website: str | None = None       # personal / lab site
    research_areas: list[str] = field(default_factory=list)
    research_interests: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.department_id}:{slugify(self.name)}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d
