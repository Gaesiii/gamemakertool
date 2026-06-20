#!/usr/bin/env python3
"""
GMS2 Project Parser — Extracts architecture, GML code, and object interactions
from a GameMaker Studio 2 .yyz file (or unzipped project folder) into structured
JSON optimized as context for an LLM grader.

Usage:
    python tool.py <path_to_yyz_or_folder> [-o output.json]

Only uses Python built-in libraries.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import zipfile


# ---------------------------------------------------------------------------
# GMS2 event-type enum → human-readable name
# Reference: https://manual.gamemaker.io/monthly/en/The_Asset_Editors/Object_Properties/Event_Order.htm
# ---------------------------------------------------------------------------
EVENT_TYPE_MAP = {
    0: "Create",
    1: "Destroy",
    2: "Alarm",
    3: "Step",
    4: "Collision",
    5: "Keyboard",
    6: "Mouse",
    7: "Other",
    8: "Draw",
    9: "KeyPress",
    10: "KeyRelease",
    11: "Trigger",       # legacy
    12: "CleanUp",
    13: "Gesture",
    14: "PreCreate",
}

# Sub-event numbers that have well-known names
STEP_SUBEVENTS = {0: "Step", 1: "Step_Begin", 2: "Step_End"}
DRAW_SUBEVENTS = {
    0: "Draw",
    64: "Draw_GUI",
    65: "Draw_GUI_Begin",
    66: "Draw_GUI_End",
    72: "Draw_Begin",
    73: "Draw_End",
    74: "Draw_Pre",
    75: "Draw_Post",
    76: "Draw_Resize",
}
OTHER_SUBEVENTS = {
    2: "Other_RoomStart",
    3: "Other_RoomEnd",
    4: "Other_GameStart",
    5: "Other_GameEnd",
    7: "Other_AnimationEnd",
    8: "Other_PathEnd",
    10: "Other_UserEvent0",
    11: "Other_UserEvent1",
    12: "Other_UserEvent2",
    13: "Other_UserEvent3",
    14: "Other_UserEvent4",
    15: "Other_UserEvent5",
    25: "Other_BroadcastMessage",
    30: "Other_AnimUpdate",
    58: "Other_Async_HTTP",
    59: "Other_Async_Dialog",
    60: "Other_Async_IAP",
    62: "Other_Async_Push",
    63: "Other_Async_SaveLoad",
    66: "Other_Async_Networking",
    67: "Other_Async_Steam",
    68: "Other_Async_Social",
    69: "Other_Async_System",
    70: "Other_Async_AudioPlayback",
    71: "Other_Async_AudioRecording",
}


# ---------------------------------------------------------------------------
# Regex patterns for interaction analysis
# ---------------------------------------------------------------------------
# Spawning via instance_create_layer(x, y, layer_name_or_id, object)
# and instance_create_depth(x, y, depth, object) — 4 arguments each.
RE_SPAWN_LAYER = re.compile(
    r"instance_create_layer\s*\([^,]+,[^,]+,[^,]+,\s*(obj_\w+)",
    re.IGNORECASE,
)
RE_SPAWN_DEPTH = re.compile(
    r"instance_create_depth\s*\([^,]+,[^,]+,[^,]+,\s*(obj_\w+)",
    re.IGNORECASE,
)

# State mutation via  with (obj_xxx)  blocks
RE_WITH_BLOCK = re.compile(
    r"\bwith\s*\(\s*(obj_\w+)\s*\)",
    re.IGNORECASE,
)

# State mutation via dot notation:  obj_xxx.field =  or  obj_xxx.field += ...
RE_DOT_MUTATION = re.compile(
    r"\b(obj_\w+)\.\w+\s*[\+\-\*\/]?=",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_get(data: dict, *keys, default=None):
    """Traverse nested dicts/lists safely, returning *default* on any miss."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and isinstance(key, int) and key < len(current):
            current = current[key]
        else:
            return default
        if current is None:
            return default
    return current


def _resolve_event_name(event_type: int, event_num: int,
                        collision_obj_name: str | None = None) -> str:
    """Return a human-readable event label from GMS2 event-type + sub-number."""
    base = EVENT_TYPE_MAP.get(event_type, f"Event{event_type}")

    if event_type == 4:  # Collision
        target = collision_obj_name or f"unknown_{event_num}"
        return f"Collision_{target}"
    if event_type == 2:  # Alarm
        return f"Alarm_{event_num}"
    if event_type == 3:  # Step
        return STEP_SUBEVENTS.get(event_num, f"Step_{event_num}")
    if event_type == 8:  # Draw
        return DRAW_SUBEVENTS.get(event_num, f"Draw_{event_num}")
    if event_type == 7:  # Other
        return OTHER_SUBEVENTS.get(event_num, f"Other_{event_num}")
    if event_type == 5:  # Keyboard
        return f"Keyboard_{event_num}"
    if event_type == 9:  # KeyPress
        return f"KeyPress_{event_num}"
    if event_type == 10:  # KeyRelease
        return f"KeyRelease_{event_num}"
    if event_type == 6:  # Mouse
        return f"Mouse_{event_num}"

    return base


def _read_text(path: str) -> str:
    """Read a text file with UTF-8, replacing undecodable bytes."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _load_json(path: str) -> dict | None:
    """Load a JSON file, stripping a potential UTF-8 BOM and trailing commas."""
    text = _read_text(path)
    if not text:
        return None
    # Strip BOM
    if text.startswith("\ufeff"):
        text = text[1:]
    # GMS2 .yy files sometimes contain trailing commas — strip them.
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"  [WARN] Malformed JSON in {path}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------

def parse_yy_file(yy_path: str) -> dict | None:
    """
    Parse an object's .yy JSON file and return structured metadata.

    Returns a dict with keys:
        name, parent, default_sprite, event_map
    where event_map is {gml_filename: human_readable_event_name}.
    """
    data = _load_json(yy_path)
    if data is None:
        return None

    obj_name = data.get("name", os.path.splitext(os.path.basename(yy_path))[0])

    # --- Parent object ---
    parent_raw = _safe_get(data, "parentObjectId", "name")
    # GMS2 uses "<undefined>" or null when there is no parent
    parent = None if (not parent_raw or parent_raw == "<undefined>") else parent_raw

    # --- Default sprite ---
    sprite_raw = _safe_get(data, "spriteId", "name")
    default_sprite = None if (not sprite_raw or sprite_raw == "<undefined>") else sprite_raw

    # --- Build event map: gml_filename → readable label ---
    event_map: dict[str, str] = {}
    event_list = data.get("eventList", [])
    for ev in event_list:
        etype = ev.get("eventtype", ev.get("eventType", -1))
        enum = ev.get("enumb", ev.get("eventNum", 0))

        # Collision target
        coll_name = None
        if etype == 4:
            coll_name = _safe_get(ev, "collisionObjectId", "name")

        label = _resolve_event_name(etype, enum, coll_name)

        # GMS2 names .gml files as  <EventTypeName>_<enumb>.gml
        # e.g. Create_0.gml, Step_0.gml, Collision_0.gml
        gml_base = EVENT_TYPE_MAP.get(etype, f"Event{etype}")
        gml_filename = f"{gml_base}_{enum}.gml"

        event_map[gml_filename] = label

    return {
        "name": obj_name,
        "parent": parent,
        "default_sprite": default_sprite,
        "event_map": event_map,
    }


def extract_gml(obj_dir: str, event_map: dict[str, str]) -> dict[str, str]:
    """
    Read all .gml files in *obj_dir* and map them to human-readable event names
    using *event_map*.  Any .gml file not in the map is included with its
    filename (minus extension) as the key.

    Returns {event_label: gml_code, ...}.
    """
    events: dict[str, str] = {}

    if not os.path.isdir(obj_dir):
        return events

    for fname in os.listdir(obj_dir):
        if not fname.lower().endswith(".gml"):
            continue

        code = _read_text(os.path.join(obj_dir, fname)).strip()
        if not code:
            continue  # skip empty event files

        label = event_map.get(fname)
        if label is None:
            # Fallback: use filename without extension
            label = os.path.splitext(fname)[0]

        events[label] = code

    return events


def analyze_interactions(events: dict[str, str],
                         obj_name: str) -> dict[str, list[str]]:
    """
    Scan all GML code for an object and return interaction data.

    Returns:
        {
            "spawns":       [sorted unique obj names],
            "collides_with": [sorted unique obj names],
            "manipulates":  [sorted unique obj names],
        }
    """
    spawns: set[str] = set()
    collides_with: set[str] = set()
    manipulates: set[str] = set()

    for label, code in events.items():
        # --- Collisions (from event labels) ---
        if label.startswith("Collision_"):
            target = label[len("Collision_"):]
            if target:
                collides_with.add(target)

        # --- Spawns ---
        for m in RE_SPAWN_LAYER.findall(code):
            spawns.add(m)
        for m in RE_SPAWN_DEPTH.findall(code):
            spawns.add(m)

        # --- Manipulates ---
        for m in RE_WITH_BLOCK.findall(code):
            if m != obj_name:
                manipulates.add(m)
        for m in RE_DOT_MUTATION.findall(code):
            if m != obj_name:
                manipulates.add(m)

    # Also scan for place_meeting / instance_place / collision_ patterns that
    # reference other objects — these imply collision checks in code.
    all_code = "\n".join(events.values())
    code_collision_funcs = re.findall(
        r"\b(?:place_meeting|instance_place|collision_[a-z_]+)\s*\([^)]*\b(obj_\w+)\b",
        all_code,
        re.IGNORECASE,
    )
    for obj in code_collision_funcs:
        if obj != obj_name:
            collides_with.add(obj)

    return {
        "spawns": sorted(spawns),
        "collides_with": sorted(collides_with),
        "manipulates": sorted(manipulates),
    }


# ---------------------------------------------------------------------------
# Project-level orchestration
# ---------------------------------------------------------------------------

def _detect_project_name(project_root: str) -> str:
    """Try to read the project name from the .yyp file in *project_root*."""
    for fname in os.listdir(project_root):
        if fname.lower().endswith(".yyp"):
            data = _load_json(os.path.join(project_root, fname))
            if data and "name" in data:
                return data["name"]
            return os.path.splitext(fname)[0]
    return os.path.basename(os.path.normpath(project_root))


def process_project(project_root: str) -> dict:
    """
    Walk the objects/ directory inside *project_root*, parse every object,
    and return the full JSON structure.
    """
    project_name = _detect_project_name(project_root)
    objects_dir = os.path.join(project_root, "objects")

    result: dict = {
        "project_name": project_name,
        "objects": {},
    }

    if not os.path.isdir(objects_dir):
        print(f"  [WARN] No 'objects/' directory found in {project_root}",
              file=sys.stderr)
        return result

    # Each sub-folder in objects/ is one object
    for obj_folder in sorted(os.listdir(objects_dir)):
        obj_dir = os.path.join(objects_dir, obj_folder)
        if not os.path.isdir(obj_dir):
            continue

        # Locate the .yy file
        yy_path = os.path.join(obj_dir, f"{obj_folder}.yy")
        if not os.path.isfile(yy_path):
            # Some projects may have a differently named .yy; try first match
            yy_files = [f for f in os.listdir(obj_dir) if f.endswith(".yy")]
            if not yy_files:
                print(f"  [WARN] No .yy file in {obj_dir}, skipping.",
                      file=sys.stderr)
                continue
            yy_path = os.path.join(obj_dir, yy_files[0])

        meta = parse_yy_file(yy_path)
        if meta is None:
            continue

        obj_name = meta["name"]
        event_map = meta["event_map"]

        events = extract_gml(obj_dir, event_map)
        interactions = analyze_interactions(events, obj_name)

        result["objects"][obj_name] = {
            "parent": meta["parent"],
            "default_sprite": meta["default_sprite"],
            "events": events,
            "interactions": interactions,
        }

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract GMS2 project structure & code into JSON for LLM grading.",
    )
    parser.add_argument(
        "input",
        help="Path to a .yyz file or an unzipped GMS2 project folder.",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output JSON file path.  Defaults to <project_name>_parsed.json.",
    )
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)

    if not os.path.exists(input_path):
        print(f"Error: '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # ----- Determine if .yyz or folder -----
    if zipfile.is_zipfile(input_path) or input_path.lower().endswith(".yyz"):
        print(f"Opening .yyz archive: {input_path}")
        try:
            with tempfile.TemporaryDirectory(prefix="gms2_") as tmp_dir:
                with zipfile.ZipFile(input_path, "r") as zf:
                    zf.extractall(tmp_dir)
                # The archive may have a single root folder or files at root
                entries = os.listdir(tmp_dir)
                yyp_at_root = any(e.endswith(".yyp") for e in entries)
                if not yyp_at_root and len(entries) == 1:
                    project_root = os.path.join(tmp_dir, entries[0])
                else:
                    project_root = tmp_dir
                result = process_project(project_root)
        except zipfile.BadZipFile:
            print(f"Error: '{input_path}' is not a valid zip/yyz file.",
                  file=sys.stderr)
            sys.exit(1)
    elif os.path.isdir(input_path):
        print(f"Reading project folder: {input_path}")
        result = process_project(input_path)
    else:
        print(f"Error: '{input_path}' is neither a .yyz file nor a directory.",
              file=sys.stderr)
        sys.exit(1)

    # ----- Write output -----
    out_path = args.output
    if out_path is None:
        safe_name = re.sub(r"[^\w\-.]", "_", result["project_name"])
        out_path = f"{safe_name}_parsed.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    obj_count = len(result["objects"])
    print(f"Done -- {obj_count} object(s) extracted -> {out_path}")


if __name__ == "__main__":
    main()
