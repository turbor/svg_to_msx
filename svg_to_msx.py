#!/usr/bin/env python3
"""
svg_to_grid.py — SVG Path Converter
================================================
Reads an Inkscape SVG file and converts all <path> elements into a text file
with one integer coordinate pair per line, mapped to the range [0, 255].

Output format:
  x y          — one coordinate per line
  *            — end of a CLOSED path (ends with 'z' or 'Z')
  **           — end of an OPEN (unclosed) path

Usage:
  python3 svg_to_grid.py input.svg [output.txt]

If no output filename is given, the output is written to <input_stem>.txt
"""

import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path

BASICPROGRAM = [
  '10 DEFINTA-Y:SCREEN 5,0:P=1:Q=0',
  '20 FOR I=1TO30:Z=I/30:RESTORE:GOSUB 50:NEXT',
  '30 GOTO 30',
  '40 LINE(X,Y)-(E,F):GOTO60',
  '50 SETPAGE P,Q:R=P:P=Q:Q=R:CLS',
  '60 READ X,Y',
  '70 X=128+Z*(X-128)',
  '80 Y=106+Z*(Y-106)',
  '90 E=X:F=Y',
  '100 READ A$,B$',
  '110 IF A$="END" THEN RETURN',
  '120 IF A$="*" THEN GOTO 40',
  '130 IF A$="**" THEN GOTO 60',
  '140 V=VAL(A$):W=VAL(B$)',
  '150 V=128+Z*(V-128)',
  '160 W=106+Z*(W-106)',
  '170 LINE(X,Y)-(V,W)',
  '180 X=V:Y=W:GOTO 100',
]

# ---------------------------------------------------------------------------
# SVG path command parser
# ---------------------------------------------------------------------------

def parse_numbers(s):
    """Extract all numbers (including negatives and floats) from a string."""
    return [float(x) for x in re.findall(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", s)]


def tokenize_path(d):
    """
    Tokenize an SVG path 'd' attribute into (command, [args]) pairs.
    Handles implicit repeated commands correctly.
    """
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
    """Split a flat list of args into chunks of size n."""
    return [args[i:i+n] for i in range(0, len(args), n)]


def path_to_points(d):
    """
    Convert an SVG path 'd' string into a list of absolute (x, y) coordinates
    and a boolean indicating whether the path is closed.

    Returns: (points: list[tuple[float,float]], closed: bool)

    Note: For curves (C, S, Q, T, A) only the endpoint is recorded.
    This gives the skeleton of the path at grid resolution. If you need
    intermediate curve samples, set CURVE_SAMPLES > 0 below.
    """
    commands = tokenize_path(d)
    points = []
    closed = False

    cx, cy = 0.0, 0.0   # current position
    sx, sy = 0.0, 0.0   # start of current subpath (for Z)
    prev_ctrl = None     # for smooth bezier reflection (S/s, T/t)

    for cmd, args in commands:

        if cmd == 'M':
            pairs = split_args(args, 2)
            for i, (x, y) in enumerate(pairs):
                cx, cy = x, y
                if i == 0:
                    sx, sy = cx, cy
                points.append((cx, cy))
            prev_ctrl = None

        elif cmd == 'm':
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

    return points, closed


# ---------------------------------------------------------------------------
# SVG viewBox parser
# ---------------------------------------------------------------------------

def get_viewbox(root):
    """
    Extract (min_x, min_y, width, height) from the SVG viewBox attribute.
    Falls back to width/height attributes if viewBox is absent.
    """
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
# Coordinate mapping
# ---------------------------------------------------------------------------

def map_coord(value, min_val, extent):
    """Map a raw SVG coordinate to an integer in [0, 255]."""
    if extent == 0:
        return 0
    normalized = (value - min_val) / extent
    normalized = max(0.0, min(1.0, normalized))
    return round(normalized * 255)


# ---------------------------------------------------------------------------
# SVG namespace helper
# ---------------------------------------------------------------------------

SVG_NS = "http://www.w3.org/2000/svg"

def find_paths(root):
    """Yield all <path> elements anywhere in the SVG tree."""
    paths = root.findall(f".//{{{SVG_NS}}}path")
    if not paths:
        paths = root.findall(".//path")
    return paths


#
# Format items as groups on wrapped lines.
#
from typing import Sequence, Callable, Optional, List, Any

def format_grouped_wrapped(
    items: Sequence[Any],
    *,
    group_size: int = 2,
    max_width: Optional[int] = 80,          # content width, excluding prefix/line number
    groups_per_line: Optional[int] = None,  # set this OR max_width (or both)
    intra_sep: str = ',',                   # inside a group, e.g., "1,2"
    group_sep: str = ' ',                   # between groups, e.g., "1,2 3,4"
    line_prefix: str = '',                  # added at the start of every line
    number_lines: bool = False,             # add "0001: " style numbering
    number_fmt: str = '{num:04d}: ',        # formatting for the line number
    formatter: Optional[Callable[[Any], str]] = None,  # item -> str (e.g., hex)
    allow_overflow_long_group: bool = True  # if a single group is longer than available width
) -> list[str]:
    """
    Format items as groups on wrapped lines.

    Rules:
    - Items are grouped by `group_size` without splitting a group across lines.
    - Items inside a group are joined by `intra_sep` (default ',').
    - Groups are joined by `group_sep` (default ' ').
    - Wrap by `max_width` **for content only** (prefix and line number are excluded from width),
      and/or enforce a fixed `groups_per_line`.
    - If a single group doesn't fit on an empty line:
        - If `allow_overflow_long_group=True`, that group is placed on its own line even if it exceeds `max_width`.
        - Otherwise, a ValueError is raised.
    """
    if group_size <= 0:
        raise ValueError("group_size must be > 0")
    if max_width is None and groups_per_line is None:
        # No wrapping: put all groups on one line
        groups_per_line = float('inf')

    fmt = formatter or (lambda x: str(x))

    # Pre-render groups (so width check is exact)
    groups: List[str] = []
    i = 0
    n = len(items)
    while i < n:
        grp_items = items[i:i + group_size]
        grp_str = intra_sep.join(fmt(v) for v in grp_items)
        groups.append(grp_str)
        i += len(grp_items)

    lines: List[str] = []
    g_idx = 0
    line_no = 1

    while g_idx < len(groups):
        prefix = (number_fmt.format(num=line_no) if number_lines else '') + line_prefix
        avail = None
        if max_width is not None:
            avail = max_width - len(prefix)
            if avail <= 0:
                raise ValueError("max_width too small for the given prefix/line number.")

        content = ''
        count_this_line = 0

        while g_idx < len(groups):
            if groups_per_line is not None and count_this_line >= groups_per_line:
                break

            g = groups[g_idx]
            new_len = len(g) if content == '' else len(content) + len(group_sep) + len(g)

            if avail is None or new_len <= avail:
                content = g if content == '' else content + group_sep + g
                g_idx += 1
                count_this_line += 1
            else:
                if content == '':  # group doesn't fit even on an empty line
                    if allow_overflow_long_group:
                        content = g
                        g_idx += 1
                        count_this_line += 1
                    else:
                        raise ValueError(
                            f"Single group of length {len(g)} exceeds available width {avail}."
                        )
                break

        lines.append(prefix + content)
        line_no += 1

    return lines

# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_svg(svg_path, out_path):
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

    lines = []
    lines.extend(BASICPROGRAM)
    msxpathpoints = []
    for i, path_el in enumerate(paths):
        d = path_el.get("d", "").strip()
        pid = path_el.get("id", f"#{i+1}")
        if not d:
            print(f"  [{pid}] empty 'd' attribute — skipped")
            continue

        points, closed = path_to_points(d)

        if not points:
            print(f"  [{pid}] no points extracted — skipped")
            continue

        status = "closed (*)" if closed else "open (**)"
        print(f"  [{pid}] {len(points)} point(s), {status}")

        if len(points) > 400:
            print(f"  [{pid}] too many points in path — skipping")
            continue

        for (x, y) in points:
            gx = map_coord(x, vb_min_x, vb_width)
            gy = map_coord(y, vb_min_y, vb_height)
            msxpathpoints.extend([gx,gy])
        msxpathpoints.extend(["*","*"] if closed else ["**","**"])

    msxpathpoints.extend(["0","0","END","END"])
    for nr,line in enumerate(format_grouped_wrapped(msxpathpoints, group_sep=", ",max_width=61)):
        lines.append(str(1000+nr*10) + " DATA " + line)


    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nOutput   : {out_path}  ({len(lines)} lines)")


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

    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else svg_path.with_suffix(".txt")

    convert_svg(svg_path, out_path)


if __name__ == "__main__":
    main()
