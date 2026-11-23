"""Building graph: the neutral model every pipeline step reads and writes.

Conventions
-----------
- Units: millimetres. Z is up. Origin is the project base point.
- Every element records where it came from (`source`) and how sure we are (`confidence`).
- IFC and Revit are *exports* of this graph. Nothing downstream edits them directly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "0.1.0"

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]


# ---------------------------------------------------------------- enums
class Source(str, Enum):
    observed = "observed"            # seen directly in the scan or the 360 frames
    inferred = "inferred"            # deduced (code rules, hidden wiring, gaps)
    from_drawings = "from_drawings"  # taken from uploaded legacy drawings
    user = "user"                    # created or overridden by a person in review


class Discipline(str, Enum):
    architecture = "architecture"
    structure = "structure"
    electrical = "electrical"
    lighting = "lighting"
    plumbing = "plumbing"
    fire = "fire"
    hvac = "hvac"


class QAStatus(str, Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"
    accepted = "accepted"  # failed tolerance but a person accepted it


# ---------------------------------------------------------------- shared parts
class Evidence(BaseModel):
    """What the decision was based on, so reviewers and agents can trace it."""
    point_count: int = 0
    frame_ids: list[str] = Field(default_factory=list)   # 360 / phone frames that show it
    drawing_refs: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class QA(BaseModel):
    status: QAStatus = QAStatus.pending
    deviation_mean_mm: Optional[float] = None
    deviation_max_mm: Optional[float] = None
    tolerance_mm: Optional[float] = None


class ExportRefs(BaseModel):
    ifc_guid: Optional[str] = None
    revit_element_id: Optional[int] = None
    revit_unique_id: Optional[str] = None


class ElementBase(BaseModel):
    id: str
    level_id: str
    discipline: Discipline
    source: Source = Source.observed
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    type_id: Optional[str] = None
    name: Optional[str] = None
    evidence: Evidence = Field(default_factory=Evidence)
    qa: QA = Field(default_factory=QA)
    exports: ExportRefs = Field(default_factory=ExportRefs)
    params: dict[str, Union[str, float, int, bool]] = Field(default_factory=dict)


# ---------------------------------------------------------------- architecture / structure
class Wall(ElementBase):
    category: Literal["wall"] = "wall"
    discipline: Discipline = Discipline.architecture
    baseline: tuple[Point2, Point2]          # centreline start -> end
    thickness: float = Field(gt=0)
    height: float = Field(gt=0)
    base_offset: float = 0.0
    exterior: bool = False
    joined_to: list[str] = Field(default_factory=list)


class Slab(ElementBase):
    """Floor slab or ceiling. `kind` decides which."""
    category: Literal["slab"] = "slab"
    discipline: Discipline = Discipline.architecture
    kind: Literal["floor", "ceiling", "roof"] = "floor"
    boundary: list[Point2] = Field(min_length=3)
    thickness: float = Field(gt=0)
    offset: float = 0.0                       # top of slab relative to level elevation


class Opening(ElementBase):
    """Door, window or plain opening, hosted in a wall."""
    category: Literal["door", "window", "opening"]
    discipline: Discipline = Discipline.architecture
    host_id: str
    offset_along: float = Field(ge=0)         # from wall baseline start to opening centre
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    sill: float = 0.0
    flip_facing: bool = False
    flip_hand: bool = False


class Column(ElementBase):
    category: Literal["column"] = "column"
    discipline: Discipline = Discipline.structure
    centre: Point2
    profile: Literal["rect", "round"] = "rect"
    width: float = Field(gt=0)
    depth: Optional[float] = None
    height: float = Field(gt=0)
    rotation_deg: float = 0.0


class Room(ElementBase):
    category: Literal["room"] = "room"
    discipline: Discipline = Discipline.architecture
    boundary: list[Point2] = Field(min_length=3)
    number: Optional[str] = None


# ---------------------------------------------------------------- MEP
class Fixture(ElementBase):
    """Point-based MEP item: light, socket, switch, panel, diffuser, sprinkler, equipment."""
    category: Literal[
        "light_fixture", "socket", "switch", "panel",
        "air_terminal", "sprinkler", "plumbing_fixture", "equipment",
    ]
    position: Point3
    rotation_deg: float = 0.0
    host_id: Optional[str] = None             # wall or ceiling it mounts on
    system_ids: list[str] = Field(default_factory=list)


class Run(ElementBase):
    """Linear MEP element: pipe, duct, conduit, cable tray."""
    category: Literal["pipe", "duct", "conduit", "cable_tray"]
    path: list[Point3] = Field(min_length=2)
    diameter: Optional[float] = None          # round sections
    width: Optional[float] = None             # rectangular sections
    height: Optional[float] = None
    system_id: Optional[str] = None
    connects_to: list[str] = Field(default_factory=list)  # other runs or fixtures

    @model_validator(mode="after")
    def _section(self):
        if self.diameter is None and (self.width is None or self.height is None):
            raise ValueError(f"{self.id}: give diameter, or width and height")
        return self


Element = Annotated[
    Union[Wall, Slab, Opening, Column, Room, Fixture, Run],
    Field(discriminator="category"),
]


# ---------------------------------------------------------------- top level
class Level(BaseModel):
    id: str
    name: str
    elevation: float
    height: float = Field(gt=0)


class ElementType(BaseModel):
    """Maps a graph type to a Revit family/type and an IFC class."""
    id: str
    category: str
    name: str
    revit_family: Optional[str] = None
    revit_type: Optional[str] = None
    ifc_class: Optional[str] = None
    params: dict[str, Union[str, float, int, bool]] = Field(default_factory=dict)


class System(BaseModel):
    id: str
    discipline: Discipline
    kind: str                                 # e.g. domestic_cold_water, sanitary, supply_air, lighting_circuit
    name: str
    source: Source = Source.observed
    panel_id: Optional[str] = None            # electrical circuits


class Question(BaseModel):
    """Raised by an agent when it can't decide; answered by a person in review."""
    id: str
    asked_by: str
    text: str
    element_ids: list[str] = Field(default_factory=list)
    frame_ids: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None


class Edit(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    by: str                                   # agent name or user id
    summary: str
    element_ids: list[str] = Field(default_factory=list)


class SourceFile(BaseModel):
    id: str
    kind: Literal["pointcloud", "video360", "images", "drawing"]
    device: Literal["terrestrial_lidar", "iphone_lidar", "android_camera", "camera_360", "other"]
    filename: str
    format: str
    bytes: Optional[int] = None


class Project(BaseModel):
    id: str
    name: str
    units: Literal["mm"] = "mm"
    target_lod: Literal[200, 300, 350] = 300
    disciplines: list[Discipline] = Field(default_factory=lambda: [Discipline.architecture])
    sources: list[SourceFile] = Field(default_factory=list)


class BuildingGraph(BaseModel):
    schema_version: str = SCHEMA_VERSION
    project: Project
    levels: list[Level] = Field(default_factory=list)
    types: list[ElementType] = Field(default_factory=list)
    systems: list[System] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    history: list[Edit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self):
        level_ids = {l.id for l in self.levels}
        el_ids = [e.id for e in self.elements]
        dupes = {i for i in el_ids if el_ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate element ids: {sorted(dupes)}")
        ids = set(el_ids)
        type_ids = {t.id for t in self.types}
        sys_ids = {s.id for s in self.systems}
        for e in self.elements:
            if e.level_id not in level_ids:
                raise ValueError(f"{e.id}: unknown level {e.level_id}")
            if e.type_id and e.type_id not in type_ids:
                raise ValueError(f"{e.id}: unknown type {e.type_id}")
            host = getattr(e, "host_id", None)
            if host and host not in ids:
                raise ValueError(f"{e.id}: unknown host {host}")
            if isinstance(e, Opening) and not isinstance(self.get(host), Wall):
                raise ValueError(f"{e.id}: openings must be hosted in a wall")
            sid = getattr(e, "system_id", None)
            if sid and sid not in sys_ids:
                raise ValueError(f"{e.id}: unknown system {sid}")
            for s in getattr(e, "system_ids", []):
                if s not in sys_ids:
                    raise ValueError(f"{e.id}: unknown system {s}")
        return self

    # helpers
    def get(self, element_id: Optional[str]):
        return next((e for e in self.elements if e.id == element_id), None)

    def by_category(self, *cats: str):
        return [e for e in self.elements if e.category in cats]

    def summary(self) -> dict:
        out: dict[str, dict[str, int]] = {}
        for e in self.elements:
            d = out.setdefault(e.category, {s.value: 0 for s in Source})
            d[e.source.value] += 1
        return out
