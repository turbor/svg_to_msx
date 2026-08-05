#!/usr/bin/env python3
"""
svg_to_grid.py -- SVG Path Converter
================================================
Reads an Inkscape SVG file and converts all <path> elements into a text file
with one integer coordinate pair per line, mapped to the range [0, 255].

Output format:
  x y          -- one coordinate per line
  *            -- end of a CLOSED path (ends with 'z' or 'Z')
  **           -- end of an OPEN (unclosed) path

Usage:
  python3 svg_to_grid.py input.svg [output.txt]

If no output filename is given, the output is written to <input_stem>.txt
"""

import sys
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# MSX-BASIC program template
# ---------------------------------------------------------------------------
# This is a complete MSX-BASIC program that animates a zoom-in effect.
# It reads coordinate DATA statements (appended later) and draws lines
# using double-buffered page flipping (SETPAGE P,Q swaps visible/draw pages).
#
# The animation loop (line 20) interpolates coordinates from the center of
# the screen outward over 30 frames using factor Z=I/30.
# Lines 70-80 and 150-160 apply the zoom: each coordinate is scaled relative
# to the screen center (128, 106) by factor Z.
#
# DATA format expected at the end:
#   x,y pairs     -- consecutive points to draw lines between
#   "*","*"       -- signals a closed path: draw line back to first point, then start new path
#   "**","**"     -- signals an open path: just start a new path without closing
#   "END","END"   -- terminates the data
# ---------------------------------------------------------------------------
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
# SVG paths use a compact mini-language in the 'd' attribute of <path> elements.
# Each command is a single letter followed by numeric arguments:
#
#   Uppercase = absolute coordinates (relative to the SVG canvas origin)
#   Lowercase = relative coordinates (relative to the current pen position)
#
# Command summary:
#   M/m x,y         -- Move to (start a new subpath)
#   L/l x,y         -- Line to
#   H/h x           -- Horizontal line (only x changes)
#   V/v y           -- Vertical line (only y changes)
#   C/c x1,y1 x2,y2 x,y  -- Cubic Bezier (two control points + endpoint)
#   S/s x2,y2 x,y  -- Smooth cubic Bezier (reflects previous control point)
#   Q/q x1,y1 x,y  -- Quadratic Bezier (one control point + endpoint)
#   T/t x,y         -- Smooth quadratic Bezier (reflects previous control point)
#   A/a rx ry rot large-arc sweep x,y -- Elliptical arc
#   Z/z             -- Close path (line back to last M position)
#
# Numbers can be separated by commas or whitespace, and negative signs act
# as implicit separators (e.g., "10-5" means "10, -5").
# ---------------------------------------------------------------------------

def parse_numbers(s):
    """Extract all numbers (including negatives and floats) from a string."""
    return [float(x) for x in re.findall(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", s)]


def tokenize_path(d):
    """
    Tokenize an SVG path 'd' attribute into (command, [args]) pairs.
    Handles implicit repeated commands correctly.
    """
    # The regex alternation matches either a command letter or a number.
    # This handles the SVG spec's rule that repeated coordinates after a command
    # letter implicitly repeat that command (e.g., "L 1,2 3,4" = "L 1,2 L 3,4").
    tokens = re.findall(r"([MmZzLlHhVvCcSsQqTtAa])|([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", d)

    commands = []
    current_cmd = None
    current_args = []

    for letter, number in tokens:
        if letter:
            # New command letter encountered - flush the previous command
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

    cx, cy = 0.0, 0.0   # current pen position
    sx, sy = 0.0, 0.0   # start of current subpath (where Z will return to)
    prev_ctrl = None     # last control point for smooth bezier reflection (S/s, T/t)

    for cmd, args in commands:

        # --- Move To ---
        # M: absolute move. First pair sets subpath start; subsequent pairs
        #    are implicitly treated as Line-To (SVG spec behavior).
        if cmd == 'M':
            pairs = split_args(args, 2)
            for i, (x, y) in enumerate(pairs):
                cx, cy = x, y
                if i == 0:
                    sx, sy = cx, cy
                points.append((cx, cy))
            prev_ctrl = None

        # m: relative move (same implicit lineto behavior as M)
        elif cmd == 'm':
            pairs = split_args(args, 2)
            for i, (dx, dy) in enumerate(pairs):
                cx, cy = cx + dx, cy + dy
                if i == 0:
                    sx, sy = cx, cy
                points.append((cx, cy))
            prev_ctrl = None

        # --- Close Path ---
        # Z/z: draw a straight line back to the subpath start (last M/m position)
        elif cmd in ('Z', 'z'):
            closed = True
            cx, cy = sx, sy
            prev_ctrl = None

        # --- Line To (absolute) ---
        elif cmd == 'L':
            for x, y in split_args(args, 2):
                cx, cy = x, y
                points.append((cx, cy))
            prev_ctrl = None

        # --- Line To (relative) ---
        elif cmd == 'l':
            for dx, dy in split_args(args, 2):
                cx, cy = cx + dx, cy + dy
                points.append((cx, cy))
            prev_ctrl = None

        # --- Horizontal Line (absolute) ---
        # Only the x-coordinate changes; y stays the same.
        elif cmd == 'H':
            for x in args:
                cx = x
                points.append((cx, cy))
            prev_ctrl = None

        # --- Horizontal Line (relative) ---
        elif cmd == 'h':
            for dx in args:
                cx += dx
                points.append((cx, cy))
            prev_ctrl = None

        # --- Vertical Line (absolute) ---
        # Only the y-coordinate changes; x stays the same.
        elif cmd == 'V':
            for y in args:
                cy = y
                points.append((cx, cy))
            prev_ctrl = None

        # --- Vertical Line (relative) ---
        elif cmd == 'v':
            for dy in args:
                cy += dy
                points.append((cx, cy))
            prev_ctrl = None

        # --- Cubic Bezier (absolute) ---
        # 6 args per segment: x1,y1 (ctrl1), x2,y2 (ctrl2), x,y (endpoint)
        # We only record the endpoint; the curve shape is lost in this conversion.
        elif cmd == 'C':
            for seg in split_args(args, 6):
                if len(seg) == 6:
                    prev_ctrl = (seg[2], seg[3])  # second control point (for S reflection)
                    cx, cy = seg[4], seg[5]
                    points.append((cx, cy))

        # --- Cubic Bezier (relative) ---
        elif cmd == 'c':
            for seg in split_args(args, 6):
                if len(seg) == 6:
                    prev_ctrl = (cx + seg[2], cy + seg[3])
                    cx, cy = cx + seg[4], cy + seg[5]
                    points.append((cx, cy))

        # --- Smooth Cubic Bezier (absolute) ---
        # 4 args: x2,y2 (ctrl2), x,y (endpoint)
        # The first control point is reflected from the previous curve's ctrl2.
        elif cmd == 'S':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (seg[0], seg[1])
                    cx, cy = seg[2], seg[3]
                    points.append((cx, cy))

        # --- Smooth Cubic Bezier (relative) ---
        elif cmd == 's':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (cx + seg[0], cy + seg[1])
                    cx, cy = cx + seg[2], cy + seg[3]
                    points.append((cx, cy))

        # --- Quadratic Bezier (absolute) ---
        # 4 args: x1,y1 (single control point), x,y (endpoint)
        elif cmd == 'Q':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (seg[0], seg[1])
                    cx, cy = seg[2], seg[3]
                    points.append((cx, cy))

        # --- Quadratic Bezier (relative) ---
        elif cmd == 'q':
            for seg in split_args(args, 4):
                if len(seg) == 4:
                    prev_ctrl = (cx + seg[0], cy + seg[1])
                    cx, cy = cx + seg[2], cy + seg[3]
                    points.append((cx, cy))

        # --- Smooth Quadratic Bezier (absolute) ---
        # 2 args: x,y (endpoint only). Control point is reflected from previous.
        elif cmd == 'T':
            for x, y in split_args(args, 2):
                prev_ctrl = None
                cx, cy = x, y
                points.append((cx, cy))

        # --- Smooth Quadratic Bezier (relative) ---
        elif cmd == 't':
            for dx, dy in split_args(args, 2):
                prev_ctrl = None
                cx, cy = cx + dx, cy + dy
                points.append((cx, cy))

        # --- Elliptical Arc (absolute) ---
        # 7 args: rx, ry, x-rotation, large-arc-flag, sweep-flag, x, y
        # Only the endpoint is recorded; the arc geometry is not approximated.
        elif cmd == 'A':
            for seg in split_args(args, 7):
                if len(seg) == 7:
                    cx, cy = seg[5], seg[6]
                    points.append((cx, cy))
            prev_ctrl = None

        # --- Elliptical Arc (relative) ---
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
# The viewBox attribute defines the coordinate system of the SVG canvas.
# Format: "min-x min-y width height"
# For example, viewBox="0 0 100 200" means the SVG uses coordinates from
# (0,0) to (100,200). All path coordinates are relative to this space.
# If viewBox is absent, we fall back to the width/height attributes on
# the <svg> element (which may include unit suffixes like "px" or "mm").
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
# The MSX SCREEN 5 has a resolution of 256x212 pixels.
# We map all SVG coordinates into the range [0, 255] so they fit in a single
# byte and can be directly used as screen coordinates on the MSX.
# ---------------------------------------------------------------------------

def map_coord(value, min_val, extent):
    """Map a raw SVG coordinate to an integer in [0, 255]."""
    if extent == 0:
        return 0
    normalized = (value - min_val) / extent
    normalized = max(0.0, min(1.0, normalized))
    return round(normalized * 255)

# ---------------------------------------------------------------------------
# Coordinate mapping for the POP (Prince of Persia) intro format.
# Same idea but the result is centered around zero: -127 <= result <= 127.
# This allows signed-byte storage in Z80 assembly, where the intro engine
# draws paths relative to a screen-center origin.
# ---------------------------------------------------------------------------

def map_pop_coord(value, min_val, extent):
    """Map a raw SVG coordinate to an integer in [0, 255]."""
    if extent == 0:
        return 0
    normalized = (value - min_val ) / extent
    normalized = max(0.0, min(1.0, normalized)) - 0.5
    return round(normalized * 255)


# ---------------------------------------------------------------------------
# SVG namespace helper
# ---------------------------------------------------------------------------
# SVG elements in well-formed XML files live in the namespace
# "http://www.w3.org/2000/svg". When searching with ElementTree's find/findall,
# we must include the namespace prefix. If that fails (e.g., the file lacks
# a namespace declaration), we retry without it.
# ---------------------------------------------------------------------------

SVG_NS = "http://www.w3.org/2000/svg"

def find_paths(root):
    """Yield all <path> elements anywhere in the SVG tree."""
    paths = root.findall(f".//{{{SVG_NS}}}path")
    if not paths:
        paths = root.findall(".//path")
    return paths


# ---------------------------------------------------------------------------
# Output line formatter
# ---------------------------------------------------------------------------
# Utility to format a flat list of values into grouped, line-wrapped strings.
# Used to generate MSX-BASIC DATA lines and Z80 assembly 'db' lines where
# each output line must stay within a maximum width (e.g., 61 chars for
# MSX-BASIC's 80-column screen minus the "1000 DATA " prefix).
# ---------------------------------------------------------------------------
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

    # Pre-render each group as a string so width calculations are exact
    groups: List[str] = []
    i = 0
    n = len(items)
    while i < n:
        grp_items = items[i:i + group_size]
        grp_str = intra_sep.join(fmt(v) for v in grp_items)
        groups.append(grp_str)
        i += len(grp_items)

    # Build output lines by filling each line with as many groups as fit
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
# Main conversion: SVG -> MSX-BASIC with DATA statements
# ---------------------------------------------------------------------------
# This function produces a complete MSX-BASIC program file.
# The BASIC program template (BASICPROGRAM) goes at the top, followed by
# DATA statements starting at line 1000 (incrementing by 10).
#
# Each path from the SVG is converted to a sequence of (x,y) coordinate
# pairs mapped to [0,255]. Paths are terminated with sentinel values:
#   "*","*"     for closed paths (the BASIC program draws a closing line)
#   "**","**"   for open paths (the BASIC program just moves to the next path)
# The entire dataset ends with "END","END".
#
# The output uses DOS-style line endings (\r\n) because MSX-DOS expects them.
# ---------------------------------------------------------------------------

def convert_svg_to_basic(svg_path, out_path):
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

    # Start with the BASIC program template lines
    lines = []
    lines.extend(BASICPROGRAM)

    # Collect all coordinate data as a flat list of values
    # (alternating x,y pairs with path-end sentinels)
    msxpathpoints = []
    for i, path_el in enumerate(paths):
        d = path_el.get("d", "").strip()
        pid = path_el.get("id", f"#{i+1}")
        if not d:
            print(f"  [{pid}] empty 'd' attribute -- skipped")
            continue

        points, closed = path_to_points(d)

        if not points:
            print(f"  [{pid}] no points extracted -- skipped")
            continue

        status = "closed (*)" if closed else "open (**)"
        print(f"  [{pid}] {len(points)} point(s), {status}")

        # Guard against excessively complex paths that would overflow
        # MSX-BASIC's limited memory
        if len(points) > 400:
            print(f"  [{pid}] too many points in path -- skipping")
            continue

        # Map each SVG coordinate to the [0,255] MSX screen range
        for (x, y) in points:
            gx = map_coord(x, vb_min_x, vb_width)
            gy = map_coord(y, vb_min_y, vb_height)
            msxpathpoints.extend([gx,gy])

        # Append the path-end sentinel
        msxpathpoints.extend(["*","*"] if closed else ["**","**"])

    # Terminate the data with the END sentinel
    msxpathpoints.extend(["0","0","END","END"])

    # Format as DATA lines: pairs grouped with ", " separator,
    # max 61 chars wide to fit in MSX-BASIC's line buffer
    for nr,line in enumerate(format_grouped_wrapped(msxpathpoints, group_sep=", ",max_width=61)):
        lines.append(str(1000+nr*10) + " DATA " + line)

    # Write with DOS line endings for MSX-DOS compatibility
    with open(out_path, "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nOutput   : {out_path}  ({len(lines)} lines)")


# ---------------------------------------------------------------------------
# Conversion: SVG -> Z80 assembly data for Prince of Persia intro engine
# ---------------------------------------------------------------------------
# This function produces a .asm file with 'db' (define byte) directives
# containing indexed coordinate data, optimized for the POP intro renderer.
#
# The output format uses coordinate tables + indexed path data:
#
# 1. X-coordinate table: all unique X values used across all paths
# 2. Y-coordinate table: all unique Y values used across all paths
# 3. Path data: each point stored as (x_index, y_index) referencing the tables
#    - Paths are terminated with byte value 255
#    - Closed paths have their first point appended at the end to close the loop
#
# This indexed approach saves memory on the Z80 because coordinates that appear
# in multiple paths are stored only once. The renderer looks up actual values
# from the tables using the index bytes.
#
# Additional optimization: coordinates that appear in BOTH the X and Y tables
# are placed at the front of each table (the "common" set), so a single lookup
# table could potentially serve both axes if the renderer supports it.
# ---------------------------------------------------------------------------

def convert_svg_to_pop_intro_data_asm(svg_path, out_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()

    # Track all unique X and Y coordinates for building lookup tables
    all_x=set()
    all_y=set()

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

    # Store paths as lists of [x,y] pairs, keyed by path index
    msxpaths = defaultdict(list)
    msxclosed = dict()
    for i, path_el in enumerate(paths):
        d = path_el.get("d", "").strip()
        pid = path_el.get("id", f"#{i+1}")
        if not d:
            print(f"  [{pid}] empty 'd' attribute -- skipped")
            continue

        points, closed = path_to_points(d)
        msxclosed[i]=closed

        if not points:
            print(f"  [{pid}] no points extracted -- skipped")
            continue

        status = "closed (*)" if closed else "open (**)"
        print(f"  [{pid}] {len(points)} point(s), {status}")

        if len(points) > 400:
            print(f"  [{pid}] too many points in path -- skipping")
            continue

        # Map to signed range centered at zero (-127..127)
        for (x, y) in points:
            gx = map_pop_coord(x, vb_min_x, vb_width)
            gy = map_pop_coord(y, vb_min_y, vb_height)
            msxpaths[i].append([gx,gy])
            all_x.add(gx)
            all_y.add(gy)

    print(f"number of X: {len(all_x)}")
    print(f"number of Y: {len(all_y)}")

    # Build coordinate lookup tables with shared values at the front.
    # Values that appear in both X and Y sets are placed first ("common"),
    # then X-only values, then Y-only values. This ordering allows the
    # renderer to potentially share table space.
    common = sorted(all_x & all_y)

    list_x = common + sorted(all_x - all_y)
    list_y = common + sorted(all_y - all_x)

    # Generate assembly output
    lines=[]

    # Emit X-coordinate lookup table
    lines.append(f"; X-coordinates ({len(list_x)})")
    for nr,line in enumerate(format_grouped_wrapped(list_x, group_size=4,group_sep=", ",max_width=61)):
        lines.append(" db " + line)

    # Emit Y-coordinate lookup table
    lines.append(f"; Y-coordinates ({len(list_y)})")
    for nr,line in enumerate(format_grouped_wrapped(list_y, group_size=4,group_sep=", ",max_width=61)):
        lines.append(" db " + line)

    # Emit indexed path data
    for i in msxclosed.keys():
        lines.append(" ; path i : closed " + str(msxclosed[i]))

        # For closed paths, duplicate the first point at the end so the
        # renderer draws a closing line segment without special-case logic
        if msxclosed[i] and msxpaths[i][-1]!=msxpaths[i][0]:
                msxpaths[i].append(msxpaths[i][0])

        # Convert absolute coordinates to table indices.
        # Each point becomes (index_into_list_x, index_into_list_y).
        msxpaths[i] = [[list_x.index(x),list_y.index(y)] for x,y in msxpaths[i]]

        # Flatten to a byte stream and append 255 as end-of-path marker
        flat = [x for pair in msxpaths[i] for x in pair]
        flat.append(255)
        for nr, line in enumerate(format_grouped_wrapped(flat, group_size=4, group_sep=",  ", max_width=61)):
            lines.append(" db " + line)

    # Write with DOS line endings (consistent with MSX toolchain expectations)
    with open(out_path, "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")

    return


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
# Produces two output files from a single SVG input:
#   1. .txt  - MSX-BASIC program with DATA statements (for direct LOAD/RUN)
#   2. .asm  - Z80 assembly data tables (for the POP intro engine)
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    svg_path = Path(sys.argv[1])
    if not svg_path.exists():
        print(f"Error: file not found: {svg_path}", file=sys.stderr)
        sys.exit(1)

    # Default output name: same stem as input with .txt extension
    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else svg_path.with_suffix(".txt")

    # Generate both output formats from the same SVG
    convert_svg_to_basic(svg_path, out_path)
    convert_svg_to_pop_intro_data_asm(svg_path, out_path.with_suffix(".asm"))

if __name__ == "__main__":
    main()
