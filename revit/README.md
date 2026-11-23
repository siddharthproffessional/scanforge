# Revit builder

Revit only runs on Windows, so this part runs on your laptop (later: Autodesk's cloud automation for Revit).

## How it connects

```
VPS (ScanForge API) --graph.json--> Windows PC: Revit + Revit MCP server <--tools-- revit_builder agent
```

The `revit_builder` agent (`backend/scanforge/agents/registry.py`) gets the graph from the API and calls the Revit MCP server's tools.

## Build order and the Revit API calls behind each step

1. **Levels**: `Level.Create(doc, elevation)`
2. **Walls**: `Wall.Create(doc, Line.CreateBound(p0, p1), wallTypeId, levelId, height, 0, false, false)`; Location Line = Wall Centerline; allow joins at both ends.
3. **Floors and ceilings**: `Floor.Create(doc, curveLoops, floorTypeId, levelId)`, `Ceiling.Create(...)`
4. **Doors and windows**: `doc.Create.NewFamilyInstance(point, symbol, hostWall, level, StructuralType.NonStructural)`, with the point at `offset_along` on the baseline and the sill height set.
5. **Lights and devices**: face-based or level-based `NewFamilyInstance` at `position`.
6. **Pipes, ducts, conduit**: `Pipe.Create`, `Duct.Create`, `Conduit.Create`, `CableTray.Create` per segment, then fittings at shared connectors (`doc.Create.NewElbowFitting`).
7. **Systems and circuits**: `PipingSystem.Create`, `MechanicalSystem.Create`, `ElectricalSystem.Create`.
8. Write `SF_GraphId` and `SF_Source` shared parameters on everything; save the `.rvt`.

Units: Revit's internal unit is feet. Convert mm with `UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Millimeters)`.

## If the Revit MCP server lacks a tool

Add a small C# add-in exposing the missing call as an MCP tool, rather than having the agent work around it.
