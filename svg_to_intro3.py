#!/usr/bin/env python3
"""
svg_to_intro3.py -- SVG to object1 assembly format converter
=============================================================
Reads an Inkscape SVG file and converts all <path> elements into
Z80 assembly data in the "object1" format:

  - Indexed X coordinate pool (deduplicated, sorted)
  - Indexed Y coordinate pool (deduplicated, sorted)
  - Vertices as (x-index, y-index) pairs
  - Edges as (vertex-index, vertex-index) pairs

Coordinates are mapped to the range [-64, 64] (configurable).

Usage:
  python3 svg_to_intro3.py input.svg [output.asm]
"""

import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Configuration - coordinate range
# ---------------------------------------------------------------------------
COORD_MIN = -64
COORD_MAX = 64

# ---------------------------------------------------------------------------
# SVG path command parser
# ---------------------------------------------------------------------------

def parse_numbers(s):
    return [float(x) for x in re.findall(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", s)]


def tokenize_path(d):
    tokens = re.findall(r"([MmZzLlHhVvCcSsQqTtAa])|([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", d)
    commands = []
    current_cmd = None
    current_args = []

    for letter, number in tokens:
        if letter:
            if current_cmd is not None:
                commands.append((current_cmd, current_args))
            current_cmd = letter
            current_args = []
        elif number:
            current_args.append(float(number))

    if current_cmd is not None:
        commands.append((current_cmd, current_args))

    return commands


def split_args(args, n):
    return [args[i:i+n] for i in range(0, len(args), n)]


def path_to_subpaths(d):
    """
    Convert SVG path 'd' string into a list of subpaths.
    Each subpath is (points, closed) where points is a list of (x, y) tuples.
    A new subpath starts at each M/m command.
    Returns: list of (points, closed)
    """
    commands = tokenize_path(d)
    subpaths = []
    points = []
    closed = False

    cx, cy = 0.0, 0.0
    sx, sy = 0.0, 0.0
    prev_ctrl = None

    def flush_subpath():
        nonlocal points, closed
        if points:
            subpaths.append((points, closed))
        points = []
        closed = False

    for cmd, args in commands:
        if cmd == 'M':
            flush_subpath()
            pairs = split_args(args, 2)
            for i, (x, y) in enumerate(pairs):
                cx, cy = x, y
                if i == 0:
                    sx, sy = cx, cy
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'm':
            flush_subpath()
            pairs = split_args(args, 2)
            for i, (dx, dy) in enumerate(pairs):
                cx, cy = cx + dx, cy + dy
                if i == 0:
                    sx, sy = cx, cy
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd in ('Z', 'z'):
            closed = True
            cx, cy = sx, sy
            flush_subpath()
            prev_ctrl = None

        elif cmd == 'L':
            for x, y in split_args(args, 2):
                cx, cy = x, y
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'l':
            for dx, dy in split_args(args, 2):
                cx, cy = cx + dx, cy + dy
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'H':
            for x in args:
                cx = x
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'h':
            for dx in args:
                cx += dx
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'V':
            for y in args:
                cy = y
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'v':
            for dy in args:
                cy += dy
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'C':
            for seg in split_args(args, 6):
                if len(seg) == 6:
                    prev_ctrl = (seg[2], seg[3])
                    cx, cy = seg[4], seg[5]
                    points.append((cx, cy))

        elif cmd == 'c':
            for seg in split_args(args, 6):
                if len(seg) == 6:
                    prev_ctrl = (cx + seg[2], cy + seg[3])
                    cx, cy = cx + seg[4], cy + seg[5]
                    points.append((cx, cy))

        elif cmd == 'S':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (seg[0], seg[1])
                    cx, cy = seg[2], seg[3]
                    points.append((cx, cy))

        elif cmd == 's':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (cx + seg[0], cy + seg[1])
                    cx, cy = cx + seg[2], cy + seg[3]
                    points.append((cx, cy))

        elif cmd == 'Q':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (seg[0], seg[1])
                    cx, cy = seg[2], seg[3]
                    points.append((cx, cy))

        elif cmd == 'q':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (cx + seg[0], cy + seg[1])
                    cx, cy = cx + seg[2], cy + seg[3]
                    points.append((cx, cy))

        elif cmd == 'T':
            for x, y in split_args(args, 2):
                prev_ctrl = None
                cx, cy = x, y
                points.append((cx, cy))

        elif cmd == 't':
            for dx, dy in split_args(args, 2):
                prev_ctrl = None
                cx, cy = cx + dx, cy + dy
                points.append((cx, cy))

        elif cmd == 'A':
            for seg in split_args(args, 7):
                if len(seg) == 7:
                    cx, cy = seg[5], seg[6]
                    points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'a':
            for seg in split_args(args, 7):
                if len(seg) == 7:
                    cx, cy = cx + seg[5], cy + seg[6]
                    points.append((cx, cy))
            prev_ctrl = None

    # Flush any remaining open subpath
    flush_subpath()

    return subpaths


# ---------------------------------------------------------------------------
# SVG viewBox parser
# ---------------------------------------------------------------------------

def get_viewbox(root):
    vb = root.get("viewBox") or root.get("viewbox")
    if vb:
        nums = parse_numbers(vb)
        if len(nums) == 4:
            return tuple(nums)

    def strip_units(s):
        if not s:
            return None
        cleaned = re.sub(r"[^\d.\-eE+]", "", s)
        return float(cleaned) if cleaned else None

    w = strip_units(root.get("width"))
    h = strip_units(root.get("height"))
    if w and h:
        return (0.0, 0.0, w, h)

    raise ValueError("SVG has no viewBox or width/height attributes.")


# ---------------------------------------------------------------------------
# SVG namespace helper
# ---------------------------------------------------------------------------

SVG_NS = "http://www.w3.org/2000/svg"

def find_paths(root):
    paths = root.findall(f".//{{{SVG_NS}}}path")
    if not paths:
        paths = root.findall(".//path")
    return paths


# ---------------------------------------------------------------------------
# Coordinate mapping
# ---------------------------------------------------------------------------

def map_coord(value, min_val, extent, out_min, out_max):
    """Map a raw SVG coordinate to an integer in [out_min, out_max]."""
    if extent == 0:
        return 0
    normalized = (value - min_val) / extent
    normalized = max(0.0, min(1.0, normalized))
    return round(out_min + normalized * (out_max - out_min))


# ---------------------------------------------------------------------------
# Main conversion: SVG -> object1 assembly format
# ---------------------------------------------------------------------------

def convert_svg_to_object1(svg_path, out_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()

    try:
        vb_min_x, vb_min_y, vb_width, vb_height = get_viewbox(root)
    except ValueError as e:
        print(f"Error reading viewBox: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"viewBox  : origin=({vb_min_x}, {vb_min_y})  "
          f"size=({vb_width} x {vb_height})")

    paths = find_paths(root)
    if not paths:
        print("No <path> elements found in the SVG.", file=sys.stderr)
        sys.exit(1)

    print(f"Paths    : {len(paths)} found")

    # Collect all vertices and edges from all paths
    all_vertices = []  # list of (mapped_x, mapped_y)
    all_edges = []     # list of (vertex_index, vertex_index)

    for i, path_el in enumerate(paths):
        d = path_el.get("d", "").strip()
        pid = path_el.get("id", f"#{i+1}")
        if not d:
            print(f"  [{pid}] empty 'd' attribute -- skipped")
            continue

        subpaths = path_to_subpaths(d)

        if not subpaths:
            print(f"  [{pid}] no points extracted -- skipped")
            continue

        total_pts = sum(len(sp[0]) for sp in subpaths)
        print(f"  [{pid}] {total_pts} point(s), {len(subpaths)} subpath(s)")

        for points, closed in subpaths:
            if not points:
                continue

            # Map SVG coordinates to target range
            mapped_points = []
            for (x, y) in points:
                mx = map_coord(x, vb_min_x, vb_width, COORD_MIN, COORD_MAX)
                my = map_coord(y, vb_min_y, vb_height, COORD_MIN, COORD_MAX)
                mapped_points.append((mx, my))

            # Deduplicate consecutive identical points
            deduped = [mapped_points[0]]
            for p in mapped_points[1:]:
                if p != deduped[-1]:
                    deduped.append(p)

            # Record vertex indices (reuse existing vertex if same coordinates)
            vertex_indices = []
            for pt in deduped:
                if pt in all_vertices:
                    idx = all_vertices.index(pt)
                else:
                    all_vertices.append(pt)
                    idx = len(all_vertices) - 1
                vertex_indices.append(idx)

            # Create edges between consecutive vertices in this subpath
            for j in range(len(vertex_indices) - 1):
                v0, v1 = vertex_indices[j], vertex_indices[j + 1]
                if v0 == v1:
                    continue
                edge = (v0, v1)
                if edge not in all_edges and (v1, v0) not in all_edges:
                    all_edges.append(edge)

            # Close the subpath if needed
            if closed and len(vertex_indices) >= 2:
                v0, v1 = vertex_indices[-1], vertex_indices[0]
                if v0 != v1:
                    edge = (v0, v1)
                    if edge not in all_edges and (v1, v0) not in all_edges:
                        all_edges.append(edge)

    # Validate limits
    if len(all_vertices) == 0:
        print("Error: no vertices extracted.", file=sys.stderr)
        sys.exit(1)

    # Build deduplicated, sorted X and Y coordinate pools
    x_pool = sorted(set(v[0] for v in all_vertices))
    y_pool = sorted(set(v[1] for v in all_vertices))

    if len(x_pool) > 255:
        print(f"Error: too many unique X coordinates ({len(x_pool)}, max 255).", file=sys.stderr)
        sys.exit(1)

    if len(y_pool) > 255:
        print(f"Error: too many unique Y coordinates ({len(y_pool)}, max 255).", file=sys.stderr)
        sys.exit(1)

    if len(all_vertices) > 255:
        print(f"Error: too many vertices ({len(all_vertices)}, max 255).", file=sys.stderr)
        sys.exit(1)

    print(f"\nX pool   : {len(x_pool)} values")
    print(f"Y pool   : {len(y_pool)} values")
    print(f"Vertices : {len(all_vertices)}")
    print(f"Edges    : {len(all_edges)}")

    # Build assembly output
    lines = []
    lines.append("object1:")

    # X coordinate pool
    lines.append(f"\tdb {len(x_pool)}\t\t; number of available X coordinates")
    lines.append(f"\tdb {','.join(str(x) for x in x_pool)}\t\t; all available X coordinates")

    # Y coordinate pool
    lines.append(f"\tdb {len(y_pool)}\t\t; number of available Y coordinates")
    lines.append(f"\tdb {','.join(str(y) for y in y_pool)}\t\t; all available Y coordinates")

    # Vertices
    lines.append(f"\tdb {len(all_vertices)} ; number of vertices")
    for v in all_vertices:
        xi = x_pool.index(v[0])
        yi = y_pool.index(v[1])
        lines.append(f"\tdb {xi},{yi} ; x-index,y-index")

    # Edges
    lines.append(f"\tdw {len(all_edges)}; number of edges")
    for e in all_edges:
        lines.append(f"\tdb {e[0]},{e[1]}")

    # Write output
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nOutput   : {out_path}")

    # Visualize the result
    fig, ax = plt.subplots(1, 1, figsize=(12, 6))
    ax.set_facecolor('black')
    ax.set_xlim(COORD_MIN - 5, COORD_MAX + 5)
    ax.set_ylim(COORD_MAX + 5, COORD_MIN - 5)  # invert Y to match screen coords
    ax.set_aspect('equal')
    ax.set_title(f'{svg_path.name} - {len(all_vertices)} vertices, {len(all_edges)} edges')

    for e in all_edges:
        v0 = all_vertices[e[0]]
        v1 = all_vertices[e[1]]
        color = 'blue' if v1[1] >= v0[1] else 'green'
        ax.plot([v0[0], v1[0]], [v0[1], v1[1]], color=color, linewidth=0.8)

    for idx, v in enumerate(all_vertices):
        ax.text(v[0], v[1], str(idx), color='yellow', fontsize=9,
                ha='center', va='center')

    plt.tight_layout()
    plt.show()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    svg_path = Path(sys.argv[1])
    if not svg_path.exists():
        print(f"Error: file not found: {svg_path}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else svg_path.with_suffix(".asm")
    convert_svg_to_object1(svg_path, out_path)


if __name__ == "__main__":
    main()
