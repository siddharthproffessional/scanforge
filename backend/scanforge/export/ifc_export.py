"""Export a BuildingGraph to IFC4 with IfcOpenShell.

Every element gets a `ScanForge_Provenance` property set (source, confidence,
QA deviation) so the observed / inferred / from-drawings split survives into
any BIM tool that opens the file.
"""
from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.api as api
import numpy as np

from ..graph import BuildingGraph, Column, Fixture, Opening, Room, Run, Slab, Wall

MM = 0.001  # IfcOpenShell API functions take SI metres; the file stores millimetres

FIXTURE_CLASS = {
    "light_fixture": "IfcLightFixture",
    "socket": "IfcOutlet",
    "switch": "IfcSwitchingDevice",
    "panel": "IfcElectricDistributionBoard",
    "air_terminal": "IfcAirTerminal",
    "sprinkler": "IfcFireSuppressionTerminal",
    "plumbing_fixture": "IfcSanitaryTerminal",
    "equipment": "IfcUnitaryEquipment",
}
RUN_CLASS = {
    "pipe": "IfcPipeSegment",
    "duct": "IfcDuctSegment",
    "conduit": "IfcCableCarrierSegment",
    "cable_tray": "IfcCableCarrierSegment",
}
SYSTEM_CLASS = {"electrical": "IfcDistributionCircuit"}


def _matrix(origin, x_axis=(1.0, 0.0, 0.0), z_axis=(0.0, 0.0, 1.0)) -> np.ndarray:
    z = np.asarray(z_axis, float)
    z /= np.linalg.norm(z)
    x = np.asarray(x_axis, float)
    x = x - (x @ z) * z
    if np.linalg.norm(x) < 1e-9:
        x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
        x = x - (x @ z) * z
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, np.asarray(origin, float)
    return m


def _provenance(f, product, el):
    ps = api.run("pset.add_pset", f, product=product, name="ScanForge_Provenance")
    props = {"GraphId": el.id, "Source": el.source.value, "Confidence": float(el.confidence)}
    if el.qa.deviation_mean_mm is not None:
        props["DeviationMeanMm"] = float(el.qa.deviation_mean_mm)
    api.run("pset.edit_pset", f, pset=ps, properties=props)


def export_ifc(g: BuildingGraph, out_path: str | Path) -> Path:
    f = api.run("project.create_file", version="IFC4")
    project = api.run("root.create_entity", f, ifc_class="IfcProject", name=g.project.name)
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "MILLIMETERS"})
    model = api.run("context.add_context", f, context_type="Model")
    body = api.run("context.add_context", f, context_type="Model", context_identifier="Body",
                   target_view="MODEL_VIEW", parent=model)

    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = api.run("root.create_entity", f, ifc_class="IfcBuilding", name=g.project.name)
    api.run("aggregate.assign_object", f, relating_object=project, products=[site])
    api.run("aggregate.assign_object", f, relating_object=site, products=[building])

    storeys, elev = {}, {}
    for lv in g.levels:
        s = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=lv.name)
        s.Elevation = lv.elevation
        api.run("geometry.edit_object_placement", f, product=s,
                matrix=_matrix((0, 0, lv.elevation * MM)))
        api.run("aggregate.assign_object", f, relating_object=building, products=[s])
        storeys[lv.id], elev[lv.id] = s, lv.elevation

    systems = {}
    for sy in g.systems:
        s = api.run("system.add_system", f, ifc_class=SYSTEM_CLASS.get(sy.discipline.value, "IfcDistributionSystem"))
        s.Name = sy.name
        systems[sy.id] = s

    made: dict[str, ifcopenshell.entity_instance] = {}

    def place(product, el):
        api.run("spatial.assign_container", f, relating_structure=storeys[el.level_id], products=[product])
        _provenance(f, product, el)
        made[el.id] = product

    # walls first: openings need their hosts
    for el in g.by_category("wall"):
        w: Wall = el
        ent = api.run("root.create_entity", f, ifc_class="IfcWall", name=w.name or w.id)
        (x0, y0), (x1, y1) = w.baseline
        d = np.array([x1 - x0, y1 - y0], float)
        length = float(np.linalg.norm(d))
        # baseline is the centreline, so offset the extrusion by half the thickness
        rep = api.run("geometry.add_wall_representation", f, context=body, length=length * MM,
                      height=w.height * MM, thickness=w.thickness * MM, offset=-w.thickness / 2 * MM)
        api.run("geometry.edit_object_placement", f, product=ent,
                matrix=_matrix((x0 * MM, y0 * MM, (elev[w.level_id] + w.base_offset) * MM),
                               x_axis=(d[0], d[1], 0)))
        api.run("geometry.assign_representation", f, product=ent, representation=rep)
        place(ent, w)
    for el in g.by_category("wall"):
        for other in el.joined_to:
            if other in made and el.id < other:
                try:
                    api.run("geometry.connect_wall", f, wall1=made[el.id], wall2=made[other])
                except Exception:
                    pass  # joins are cosmetic in IFC; geometry already meets

    for el in g.elements:
        z0 = elev[el.level_id]
        if isinstance(el, Slab):
            cls = {"floor": "IfcSlab", "roof": "IfcRoof", "ceiling": "IfcCovering"}[el.kind]
            ent = api.run("root.create_entity", f, ifc_class=cls, name=el.name or el.id)
            if cls == "IfcCovering":
                ent.PredefinedType = "CEILING"
            rep = api.run("geometry.add_slab_representation", f, context=body, depth=el.thickness * MM,
                          polyline=[(x * MM, y * MM) for x, y in el.boundary])
            api.run("geometry.assign_representation", f, product=ent, representation=rep)
            top = z0 + el.offset
            api.run("geometry.edit_object_placement", f, product=ent,
                    matrix=_matrix((0, 0, (top - el.thickness) * MM)))
            place(ent, el)

        elif isinstance(el, Opening):
            host: Wall = g.get(el.host_id)
            (x0, y0), (x1, y1) = host.baseline
            d = np.array([x1 - x0, y1 - y0], float)
            d /= np.linalg.norm(d)
            n = np.array([-d[1], d[0]])
            start = np.array([x0, y0]) + d * (el.offset_along - el.width / 2) - n * host.thickness / 2
            base_z = z0 + host.base_offset + el.sill
            m = _matrix((start[0] * MM, start[1] * MM, base_z * MM), x_axis=(d[0], d[1], 0))
            void = api.run("root.create_entity", f, ifc_class="IfcOpeningElement", name=f"{el.id}-void")
            vrep = api.run("geometry.add_wall_representation", f, context=body, length=el.width * MM,
                           height=el.height * MM, thickness=host.thickness * MM)
            api.run("geometry.assign_representation", f, product=void, representation=vrep)
            api.run("geometry.edit_object_placement", f, product=void, matrix=m)
            api.run("feature.add_feature", f, feature=void, element=made[host.id])
            if el.category == "opening":
                made[el.id] = void
                continue
            cls = "IfcDoor" if el.category == "door" else "IfcWindow"
            ent = api.run("root.create_entity", f, ifc_class=cls, name=el.name or el.id)
            ent.OverallWidth, ent.OverallHeight = el.width, el.height
            if cls == "IfcDoor":
                rep = api.run("geometry.add_door_representation", f, context=body,
                              overall_width=el.width, overall_height=el.height)  # project units (mm)
            else:
                rep = api.run("geometry.add_window_representation", f, context=body,
                              overall_width=el.width, overall_height=el.height)
            if rep is not None:
                api.run("geometry.assign_representation", f, product=ent, representation=rep)
            api.run("geometry.edit_object_placement", f, product=ent, matrix=m)
            api.run("feature.add_filling", f, opening=void, element=ent)
            place(ent, el)

        elif isinstance(el, Column):
            ent = api.run("root.create_entity", f, ifc_class="IfcColumn", name=el.name or el.id)
            if el.profile == "round":
                prof = api.run("profile.add_parameterized_profile", f, ifc_class="IfcCircleProfileDef")
                prof.Radius = el.width / 2
            else:
                prof = api.run("profile.add_parameterized_profile", f, ifc_class="IfcRectangleProfileDef")
                prof.XDim, prof.YDim = el.width, el.depth or el.width
            rep = api.run("geometry.add_profile_representation", f, context=body, profile=prof, depth=el.height * MM)
            api.run("geometry.assign_representation", f, product=ent, representation=rep)
            ang = np.radians(el.rotation_deg)
            api.run("geometry.edit_object_placement", f, product=ent,
                    matrix=_matrix((el.centre[0] * MM, el.centre[1] * MM, z0 * MM), x_axis=(np.cos(ang), np.sin(ang), 0)))
            place(ent, el)

        elif isinstance(el, Room):
            ent = api.run("root.create_entity", f, ifc_class="IfcSpace", name=el.number or el.id)
            ent.LongName = el.name
            lv = next(l for l in g.levels if l.id == el.level_id)
            rep = api.run("geometry.add_slab_representation", f, context=body, depth=lv.height * MM,
                          polyline=[(x * MM, y * MM) for x, y in el.boundary])
            api.run("geometry.assign_representation", f, product=ent, representation=rep)
            api.run("geometry.edit_object_placement", f, product=ent, matrix=_matrix((0, 0, z0 * MM)))
            api.run("aggregate.assign_object", f, relating_object=storeys[el.level_id], products=[ent])
            _provenance(f, ent, el)
            made[el.id] = ent

        elif isinstance(el, Fixture):
            ent = api.run("root.create_entity", f, ifc_class=FIXTURE_CLASS[el.category], name=el.name or el.id)
            size = {"light_fixture": (600, 600, 80), "panel": (500, 200, 800)}.get(el.category, (90, 40, 90))
            rep = api.run("geometry.add_wall_representation", f, context=body, length=size[0] * MM,
                          thickness=size[1] * MM, height=size[2] * MM)
            api.run("geometry.assign_representation", f, product=ent, representation=rep)
            x, y, z = el.position
            if el.category == "light_fixture":   # hang below the ceiling point
                z -= size[2]
            api.run("geometry.edit_object_placement", f, product=ent,
                    matrix=_matrix(((x - size[0] / 2) * MM, (y - size[1] / 2) * MM, (z0 + z) * MM)))
            place(ent, el)
            for sid in el.system_ids:
                api.run("system.assign_system", f, products=[ent], system=systems[sid])

        elif isinstance(el, Run):
            cls = RUN_CLASS[el.category]
            pts = [np.array(p, float) for p in el.path]
            segs = []
            for k, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
                length = float(np.linalg.norm(b - a))
                if length < 1:
                    continue
                ent = api.run("root.create_entity", f, ifc_class=cls, name=f"{el.id}.{k + 1}")
                if el.diameter:
                    prof = api.run("profile.add_parameterized_profile", f, ifc_class="IfcCircleProfileDef")
                    prof.Radius = el.diameter / 2
                else:
                    prof = api.run("profile.add_parameterized_profile", f, ifc_class="IfcRectangleProfileDef")
                    prof.XDim, prof.YDim = el.width, el.height
                rep = api.run("geometry.add_profile_representation", f, context=body, profile=prof, depth=length * MM)
                api.run("geometry.assign_representation", f, product=ent, representation=rep)
                api.run("geometry.edit_object_placement", f, product=ent,
                        matrix=_matrix(((a[0]) * MM, (a[1]) * MM, (z0 + a[2]) * MM), z_axis=tuple(b - a)))
                api.run("spatial.assign_container", f, relating_structure=storeys[el.level_id], products=[ent])
                _provenance(f, ent, el)
                segs.append(ent)
            if el.system_id and segs:
                api.run("system.assign_system", f, products=segs, system=systems[el.system_id])
            if segs:
                made[el.id] = segs[0]

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(out))
    return out
