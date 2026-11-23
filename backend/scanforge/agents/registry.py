"""The three first-release agents. Later: family_mapper, qa_checker, and the MEP
agents (lighting/devices, electrical, piping, hvac, drawing_reader, clash_checker).

Agents share one project workspace through `Workspace`, which owns the graph file.
"""
from __future__ import annotations

from pathlib import Path

from ..export.ifc_export import export_ifc
from ..graph import BuildingGraph, Edit, Question
from ..pipeline.ingest import classify_file
from ..pipeline.run import run_pointcloud
from .base import Agent, Tool


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.graph_path = self.root / "graph.json"

    def load(self) -> BuildingGraph:
        return BuildingGraph.model_validate_json(self.graph_path.read_text())

    def save(self, g: BuildingGraph) -> None:
        self.graph_path.write_text(g.model_dump_json(indent=2))


# ---------------------------------------------------------------- orchestrator
def orchestrator(ws: Workspace) -> Agent:
    def list_inputs():
        return [{"file": p.name, **_safe_classify(p)} for p in sorted((ws.root / "inputs").glob("*"))]

    def run_architecture(file: str, default_wall_thickness: float = 200.0):
        g = run_pointcloud(ws.root / "inputs" / file, default_wall_thickness=default_wall_thickness)
        ws.save(g)
        return {"levels": [l.model_dump() for l in g.levels], "summary": g.summary()}

    def graph_summary():
        g = ws.load()
        return {"summary": g.summary(), "open_questions": [q.model_dump() for q in g.questions if not q.answer]}

    def set_param(element_ids: list[str], field: str, value: float, reason: str):
        """Change a numeric field (e.g. thickness, height) on elements, logged in history."""
        g = ws.load()
        for e in g.elements:
            if e.id in element_ids:
                setattr(e, field, value)
        g.history.append(Edit(by="orchestrator", summary=reason, element_ids=element_ids))
        g = BuildingGraph.model_validate(g.model_dump())
        ws.save(g)
        return {"changed": len(element_ids)}

    def export(fmt: str = "ifc"):
        return {"path": str(export_ifc(ws.load(), ws.root / "out" / "model.ifc"))}

    return Agent(
        name="orchestrator",
        system=(
            "You run a scan-to-BIM job. Plan the steps, call the pipeline tools, check results, "
            "and retry steps with different settings when results look wrong (e.g. no levels found, "
            "far too many or too few walls). Apply user edit requests with set_param and say exactly "
            "what changed. Never invent geometry: everything comes from tools. Keep replies short."),
        tools=[
            Tool("list_inputs", "List uploaded files and what each one is.",
                 {"type": "object", "properties": {}}, list_inputs),
            Tool("run_architecture", "Run clean -> levels -> segmentation -> wall rebuild on one point cloud.",
                 {"type": "object", "properties": {"file": {"type": "string"},
                                                   "default_wall_thickness": {"type": "number"}},
                  "required": ["file"]}, run_architecture),
            Tool("graph_summary", "Counts by category and source, plus open questions.",
                 {"type": "object", "properties": {}}, graph_summary),
            Tool("set_param", "Set a numeric field on elements, with a reason for the history log.",
                 {"type": "object", "properties": {
                     "element_ids": {"type": "array", "items": {"type": "string"}},
                     "field": {"type": "string"}, "value": {"type": "number"},
                     "reason": {"type": "string"}},
                  "required": ["element_ids", "field", "value", "reason"]}, set_param),
            Tool("export", "Export the current graph to IFC.",
                 {"type": "object", "properties": {"fmt": {"type": "string", "enum": ["ifc"]}}}, export),
        ],
    )


def _safe_classify(p: Path) -> dict:
    try:
        return classify_file(p)
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- vision reviewer
def vision_reviewer(ws: Workspace) -> Agent:
    def low_confidence(threshold: float = 0.7):
        g = ws.load()
        return [{"id": e.id, "category": e.category, "confidence": e.confidence,
                 "frames": e.evidence.frame_ids} for e in g.elements if e.confidence < threshold]

    def relabel(element_id: str, category: str, confidence: float, reason: str):
        g = ws.load()
        e = g.get(element_id)
        if e is None:
            raise ValueError(f"no element {element_id}")
        if category != e.category:
            # category changes need a geometry rebuild; record intent for the pipeline
            e.params["relabel_to"] = category
        e.confidence = confidence
        g.history.append(Edit(by="vision_reviewer", summary=reason, element_ids=[element_id]))
        ws.save(g)
        return {"ok": True}

    def ask_user(text: str, element_ids: list[str], options: list[str], frame_ids: list[str] | None = None):
        g = ws.load()
        q = Question(id=f"Q{len(g.questions) + 1}", asked_by="vision_reviewer", text=text,
                     element_ids=element_ids, options=options, frame_ids=frame_ids or [])
        g.questions.append(q)
        ws.save(g)
        return {"question_id": q.id}

    # TODO: add a `view_frames` tool returning image blocks of the frame crops
    return Agent(
        name="vision_reviewer",
        system=(
            "You review low-confidence elements using the 360 and phone frames that show them. "
            "Relabel only when the images clearly show it. If you are still unsure, ask the user "
            "with ask_user and give 2-3 short options. Never guess on doors vs openings or glass vs wall."),
        tools=[
            Tool("low_confidence", "Elements below a confidence threshold, with their frame ids.",
                 {"type": "object", "properties": {"threshold": {"type": "number"}}}, low_confidence),
            Tool("relabel", "Change an element's category/confidence after checking images.",
                 {"type": "object", "properties": {"element_id": {"type": "string"}, "category": {"type": "string"},
                                                   "confidence": {"type": "number"}, "reason": {"type": "string"}},
                  "required": ["element_id", "category", "confidence", "reason"]}, relabel),
            Tool("ask_user", "Ask the reviewer a question shown in the Review screen.",
                 {"type": "object", "properties": {"text": {"type": "string"},
                                                   "element_ids": {"type": "array", "items": {"type": "string"}},
                                                   "options": {"type": "array", "items": {"type": "string"}},
                                                   "frame_ids": {"type": "array", "items": {"type": "string"}}},
                  "required": ["text", "element_ids", "options"]}, ask_user),
        ],
    )


# ---------------------------------------------------------------- revit builder
def revit_builder(ws: Workspace, revit_tools: list[Tool]) -> Agent:
    """`revit_tools` are the Revit MCP server's tools, wrapped as `Tool`s by the MCP client
    running on the Windows machine with Revit open. See revit/README.md."""
    def graph_for_revit():
        g = ws.load()
        return {"levels": [l.model_dump() for l in g.levels],
                "types": [t.model_dump() for t in g.types],
                "elements": [e.model_dump() for e in g.elements]}

    return Agent(
        name="revit_builder",
        system=(
            "You build a native Revit model from the building graph using the Revit tools. Order: "
            "levels, walls (centreline location, join corners), floors/ceilings, hosted doors and "
            "windows, then MEP fixtures and systems. Use the mapped family/type; if a type is missing, "
            "duplicate the closest one and set its parameters. Write every element's graph id and "
            "source into shared parameters SF_GraphId and SF_Source. Report what you could not build."),
        tools=[Tool("graph_for_revit", "The building graph to build.",
                    {"type": "object", "properties": {}}, graph_for_revit), *revit_tools],
    )
