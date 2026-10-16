#!/usr/bin/env python3
"""Generate the animated header of the profile README.

One SVG per theme: the icon row, a brick wall, the contribution grid and a
snake that eats it, one meal after another, each starting where the last
ended. Every meal, at a random point, the snake stops, leaves the grid,
does one of these and comes back to carry on eating where it stopped:

  health   a cell turns amber, the status says HEALTH_WARN, the snake scrubs it
  scrub    a deep scrub: the snake walks a row it already ate, cells flash
  wall     the snake breaks through the wall, weaves between the icons, circles one
  shatter  the snake rams an icon, which bursts into shards; it goes on through
  osd      an icon goes dark and keels over; the snake bumps it back up
  octopus  tentacles reach out of the Ceph tile, grab the snake's tail and lift it
  recover  cells it just ate come back in a wave; it has to eat them again
  upgrade  ceph orch upgrade: every icon goes grey; the snake bumps each one back up

Two small tentacles live in the Ceph tile: the scout and its smaller
sibling, the kid. Whenever the snake is busy elsewhere one of them creeps
out: hides behind another tile and peeks over it with a question, crawls
along the top of the row, pokes a cell, goes down to the status line or
along under the grid, nudges a brick. Once a meal they go out together:
question and answer over two tiles, peek-a-boo, passing a stolen brick, or
the kid in a vampire cape asking for blood and getting garlic. Each event
gets a one-word remark from a safe spot. The scout is the lookout of the
octopus event: out under the tile as the snake comes, it bolts just before
the arms strike.

GitHub shows README images as plain pictures: no scripts, no external
references, nothing random at view time. So the whole cycle (event order,
where each meal is interrupted, which icon, which cell) is rolled when the
file is built, from a seed that defaults to the current UTC hour, and baked
into one long CSS animation.

  profile.py tiles                  refresh assets/tiles/ (network)
  profile.py build --out dist       needs GITHUB_TOKEN; fetches ceph's releases.yml
  profile.py build --calendar cal.json --releases releases.yml --event wall --times
  profile.py preview --out dist     build, plus preview.html with a time scrubber
  profile.py check --seeds 30       many seeds, every variant and event; CI runs it
"""

import argparse
import datetime
import json
import math
import os
import random
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TILES = ROOT / "assets" / "tiles"
USER = os.environ.get("GITHUB_USER", "lumir-sliva")

ICONS = ["ceph", "cpp", "c", "py", "bash", "go", "openstack", "gcp"]
EVENTS = ["health", "wall", "shatter", "octopus", "osd", "scrub", "recover", "upgrade"]
TITLE = "Lumir Sliva"
INTRO = "Senior Storage Engineer @Seznam.cz. I do stuff in the cloud. \u2601\ufe0f"

THEMES = {
    "dark": {
        "tile_bg": "#242938",
        "cells": ["#161b22", "#3d1716", "#66221f", "#93302b", "#bf3d37"],
        "wall": "#30363d",
        "ok": "#3fb950",
        "warn": "#d29922",
        "warn_dim": "#6a4d12",
        "ink": "#8b949e",
        "cape": "#a371f7",
        "sign": ("#161b22", "#30363d", "#e6edf3"),   # box, border, text
        "text": "#e6edf3",
        "muted": "#8b949e",
    },
    "light": {
        "tile_bg": "#f4f2ed",
        "cells": ["#ebedf0", "#f8c7c2", "#f08f85", "#e5564c", "#b8322b"],
        "wall": "#d0d7de",
        "ok": "#1a7f37",
        "warn": "#9a6700",
        "warn_dim": "#e3c67a",
        "ink": "#57606a",
        "cape": "#8250df",
        "sign": ("#ffffff", "#d0d7de", "#1f2328"),
        "text": "#1f2328",
        "muted": "#59636e",
    },
}
SNAKE = "#EF5C55"  # Ceph red
SEGMENTS = [12, 11, 9, 7]

# The cluster on the status line.
OSDS, PGS = 1337, 133700

# Schedule: MEALS meals per cycle, each interrupted once by an event.
LOOP_SECONDS = 35.0
MEALS = 7
INTERRUPT = (0.25, 0.75)                    # share of the grid eaten when it stops
LEAD = 0.6                                  # an alarm fires this long before it reacts
SCRUB = 0.9                                 # wiggling over the bad cell
DRAG = 8                                    # how far the tentacles lift the snake
DIGEST = 0.5                                # pause next to START after a meal
POP = 0.22                                  # an eaten cell pops away in POP s
REFILL = 0.3                                # a cell grows back in REFILL s

# Geometry. The snake moves between cell centres, one pitch per step.
WIDTH, HEIGHT = 880, 250                    # the animation; TOP more for the title
TOP = 70
PITCH, CELL, COLS, ROWS = 16, 12, 53, 7
X0 = (WIDTH - COLS * PITCH + (PITCH - CELL)) // 2
Y0 = 110                                    # top of the grid
LANE = -1                                   # grid row of the lane above it
TILE, TGAP = 40, 16
ROW_X = (WIDTH - (len(ICONS) * TILE + (len(ICONS) - 1) * TGAP)) // 2
ROW_Y = 22                                  # top of the icon row
ABOVE = ROW_Y - 12                          # snake centre over the icons
BELOW = ROW_Y + TILE + 12                   # snake centre under the icons
WALL_Y, BRICK, BRICK_GAP = 86, 10, 4
STATUS_Y = 240

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

CEPH_LOGO = "https://cdn.jsdelivr.net/npm/simple-icons@16.35.0/icons/ceph.svg"
CEPH_RELEASES = "https://raw.githubusercontent.com/ceph/ceph/main/doc/releases/releases.yml"
NEXT_NAMES = {"tentacle": "umbrella", "umbrella": "vampire"}     # announced, not in the file yet


def px(cell):
    c, r = cell
    return (X0 + c * PITCH + CELL / 2, Y0 + r * PITCH + CELL / 2)


def tile_x(i):
    return ROW_X + i * (TILE + TGAP)


START = (-1, LANE)
LANE_Y = px(START)[1]


def num(v):
    """Short decimal for CSS: 462 rather than 462.0."""
    return f"{v:.1f}".removesuffix(".0")


# --- tiles -------------------------------------------------------------------

def fetch(url):
    # skillicons.dev answers 403 to urllib's default User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "profile.py"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def ceph_tile(background):
    path = re.search(r' d="([^"]+)"', fetch(CEPH_LOGO)).group(1)
    # Logo is 24x24; scale it to 160 and centre it in the 256 tile.
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
            'viewBox="0 0 256 256" fill="none">'
            f'<rect width="256" height="256" rx="60" fill="{background}"/>'
            f'<g transform="translate(48 48) scale(6.6667)"><path d="{path}" fill="{SNAKE}"/></g>'
            '</svg>')


def skillicon(name, theme):
    url = f"https://skillicons.dev/icons?i={name}&theme={theme}"
    # The response wraps the tile in an outer <svg><g>; keep the inner <svg>.
    match = re.search(r"<g[^>]*>\s*(<svg.*</svg>)\s*</g>", fetch(url), re.S)
    if not match:
        sys.exit(f"unexpected skillicons response for {name}")
    return match.group(1)


def cmd_tiles(_args):
    TILES.mkdir(parents=True, exist_ok=True)
    for theme, colours in THEMES.items():
        for name in ICONS:
            svg = ceph_tile(colours["tile_bg"]) if name == "ceph" else skillicon(name, theme)
            (TILES / f"{name}-{theme}.svg").write_text(svg + "\n", encoding="utf-8")
            print(f"{name}-{theme}.svg")


def tile_symbol(name, theme):
    svg = (TILES / f"{name}-{theme}.svg").read_text(encoding="utf-8").strip()
    # Tiles share one document, so their internal ids need a prefix.
    for old in re.findall(r'id="([^"]+)"', svg):
        svg = svg.replace(f'id="{old}"', f'id="{name}-{old}"')
        svg = svg.replace(f"url(#{old})", f"url(#{name}-{old})")
    inner = re.sub(r"^<svg[^>]*>|</svg>$", "", svg, flags=re.S)
    viewbox = re.search(r'viewBox="([^"]+)"', svg).group(1)
    return f'<symbol id="tile-{name}" viewBox="{viewbox}">{inner}</symbol>'


# --- calendar ----------------------------------------------------------------

def fetch_calendar():
    query = ("query($u:String!){user(login:$u){contributionsCollection{"
             "contributionCalendar{weeks{contributionDays{contributionLevel "
             "weekday}}}}}}")
    token = os.environ.get("GITHUB_TOKEN") or sys.exit("GITHUB_TOKEN is not set")
    body = json.dumps({"query": query, "variables": {"u": USER}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", body, {
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "profile.py"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_calendar(data):
    weeks = (data["data"]["user"]["contributionsCollection"]
             ["contributionCalendar"]["weeks"])[-COLS:]
    return {(c, day["weekday"]): LEVELS[day["contributionLevel"]]
            for c, week in enumerate(weeks) for day in week["contributionDays"]}


# --- releases ----------------------------------------------------------------

def parse_releases(text):
    """Named Ceph releases from the docs' releases.yml, newest first:
    {name, version (latest), released (first stable, or None), eol (actual,
    else target, or None)}. The file is flat and hand-written, so a few
    regexes do instead of a YAML parser; the development section is skipped."""
    out, cur = [], None
    for line in text.split("\n"):
        if line.startswith("development:"):
            break
        m = re.match(r"^  (\w+):\s*$", line)
        if m:
            cur = {"name": m.group(1), "version": None, "released": None, "eol": None, "_target": None}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"^    (target_eol|actual_eol):\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            key = "eol" if m.group(1) == "actual_eol" else "_target"
            cur[key] = datetime.date.fromisoformat(m.group(2))
            continue
        m = re.match(r"^      - version:\s*['\"]?([\w.]+)", line)
        if m and cur["version"] is None:
            cur["version"] = m.group(1)
            continue
        m = re.match(r"^        released:\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            cur["released"] = datetime.date.fromisoformat(m.group(1))   # last one wins: the first stable
    for r in out:
        r["eol"] = r["eol"] or r.pop("_target")
        r.pop("_target", None)
    return out


EVERGREEN = ["upgrade?", "ceph orch upgrade?", "quincy who?", "infernalis?", "pacific. rip."]


def current_release(releases, today):
    """The newest named release that is out on a given day, or None."""
    return next((r for r in releases if r["released"] and r["released"] <= today), None)


def release_signs(releases, today):
    """What the scouts say about Ceph releases on a given day: the current
    one, the next name, what is about to go EOL and what already did."""
    out = list(EVERGREEN)
    current = current_release(releases, today)
    if current:
        out += [f"{current['name']}?", f"{current['name']} {current['version']}.",
                f"upgrade to {current['name']}?"]
        if current["name"] in NEXT_NAMES:
            out.append(f"{NEXT_NAMES[current['name']]} next?")
    for r in releases:
        if r["eol"] and today < r["eol"] <= today + datetime.timedelta(days=90):
            out.append(f"{r['name']} eol in {(r['eol'] - today).days}d")
    gone = [r["name"] for r in releases if r["eol"] and r["eol"] <= today]
    if gone:
        out.append(f"{gone[0]} -> EOL")
    if len(gone) > 1:
        out.append(f"{gone[1]}? old.")
    return out


def fetch_releases(path=None):
    """Releases from releases.yml (a saved copy, or the one in ceph/ceph);
    None if that fails, and the scouts fall back to the built-in signs."""
    try:
        text = Path(path).read_text(encoding="utf-8") if path else fetch(CEPH_RELEASES)
        return parse_releases(text)
    except (OSError, ValueError) as e:        # URLError is an OSError
        print(f"releases: {e}; using the built-in signs", file=sys.stderr)
        return None


# --- the meal ----------------------------------------------------------------

def walk(a, b):
    """Grid steps from a to b, horizontal first; excludes a, includes b."""
    (c, r), steps = a, []
    while c != b[0]:
        c += 1 if b[0] > c else -1
        steps.append((c, r))
    while r != b[1]:
        r += 1 if b[1] > r else -1
        steps.append((c, r))
    return steps


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def plan(active, start=START):
    """One meal of grid moves from start, eating every active cell, nearest
    first; cells passed over on the way are eaten too. Ends on the lane
    above the last cell.

    Returns (moves, eats): eats maps a move index to the cells eaten there.
    """
    pos, left = start, set(active)
    moves, eats = [], {}

    def go(target):
        nonlocal pos
        for step in walk(pos, target):
            moves.append(step)
            if step in left:
                left.discard(step)
                eats.setdefault(len(moves) - 1, []).append(step)
        pos = target

    while left:
        go(min(left, key=lambda p: (dist(pos, p), p)))
    go((pos[0], LANE))
    return moves, eats


# --- timeline ----------------------------------------------------------------

class Timeline:
    """Head positions (H) and frames (t, move index, wiggle).

    Segment i sits where the head was i moves ago, so a hold (frames that
    don't advance the move index) freezes the whole snake in its shape.
    """

    def __init__(self, dt):
        self.dt = dt
        self.H = [px(START)]
        self.frames = [(0.0, 0, 0)]
        self.t = 0.0

    @property
    def head(self):
        return self.H[-1]

    def step(self, point):
        self.t += self.dt
        self.H.append(point)
        self.frames.append((self.t, len(self.H) - 1, 0))
        return self.t

    def go(self, x, y):
        """Straight line to (x, y) in roughly pitch-sized steps."""
        hx, hy = self.head
        n = max(1, round(math.hypot(x - hx, y - hy) / PITCH))
        return [(self.step((hx + (x - hx) * k / n, hy + (y - hy) * k / n)),
                 self.head) for k in range(1, n + 1)]

    def hold(self, seconds, wiggle=False):
        if seconds <= 0:
            return
        m, n = len(self.H) - 1, max(2, round(seconds / 0.09))
        for k in range(1, n + 1):
            self.t += seconds / n
            self.frames.append((self.t, m, (1 if k % 2 else -1)
                                if wiggle and k < n else 0))

    def close(self):
        """Last step back to START, wrapping onto H[0]."""
        self.t += self.dt
        self.frames.append((self.t, len(self.H), 0))

    def segment(self, i):
        """(t, x, y) of segment i at every frame."""
        out = []
        for t, m, wig in self.frames:
            x, y = self.H[(m - i) % len(self.H)]
            if wig and i < len(SEGMENTS) - 1:   # the tail is held still
                y += 2 * wig * (1 if i % 2 else -1)
            out.append((t, x, y))
        return out


def simplify(points):
    """Drop frames where the motion just continues at the same velocity."""
    out = [points[0]]
    for k in range(1, len(points) - 1):
        (t0, x0, y0), (t1, x1, y1), (t2, x2, y2) = out[-1], points[k], points[k + 1]
        v1 = ((x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0))
        v2 = ((x2 - x1) / (t2 - t1), (y2 - y1) / (t2 - t1))
        if abs(v1[0] - v2[0]) > 1e-6 or abs(v1[1] - v2[1]) > 1e-6:
            out.append(points[k])
    out.append(points[-1])
    return out


# --- events ------------------------------------------------------------------

def crossing(steps, y, y_from):
    """Time the head crosses height y within a list of (t, point) steps."""
    prev = y_from
    for t, (_, hy) in steps:
        if (prev - y) * (hy - y) <= 0:
            return t
        prev = hy
    return steps[-1][0]


def weave(tl, ev, g, y):
    """Through gap g (between tiles g-1 and g) from y to the other level."""
    gx = tile_x(g) - TGAP / 2
    tl.go(gx, y)
    y = ABOVE if y == BELOW else BELOW
    steps = tl.go(gx, y)
    mid = steps[len(steps) // 2][0]
    ev["wobbles"] += [(g - 1, mid), (g, mid)]
    return y


def through_wall(tl, ev, x, up):
    """Cross the wall at x; bricks fly on the way up, the hole stays open."""
    y_from = tl.head[1]
    steps = tl.go(x, BELOW if up else LANE_Y)
    if up:
        ev["bricks"].append((x, crossing(steps, WALL_Y, y_from), True))
    return crossing(steps, WALL_Y, y_from)


def detour(kind, tl, rng, eaten, active):
    """The snake leaves its meal, does the event and comes back to the same
    spot in the same shape. Returns the event with its times."""
    shape = tl.H[-len(SEGMENTS):]
    hx, hy = tl.head
    ev = {"kind": kind, "start": tl.t, "bricks": [], "wobbles": []}
    if kind == "health":
        # A cell it already ate went bad (not one it just ate: the alarm
        # starts LEAD s before it reacts); it is somewhere behind the snake.
        far = [c for c in eaten[:-8] if abs(px(c)[0] - hx) + abs(px(c)[1] - hy) >= 4 * PITCH]
        cell = rng.choice(far or eaten[:-8] or eaten)
        cx, cy = px(cell)
        tl.go(cx, hy)
        tl.go(cx, cy)
        tl.hold(SCRUB, wiggle=True)             # it scrubs the cell
        ev["warn"] = (cell, ev["start"] - LEAD, tl.t)
    elif kind == "scrub":
        # Deep scrub: it walks one row of cells it already ate, end to end.
        rows = {}
        for c in eaten:
            rows.setdefault(c[1], []).append(c[0])
        r, cols = max(rows.items(), key=lambda kv: (len(kv[1]), -kv[0]))
        a, b = min(cols), min(max(cols), min(cols) + 15)
        if abs(hx - px((a, r))[0]) < abs(hx - px((b, r))[0]):
            a, b = b, a                         # start from the far end
        tl.go(px((a, r))[0], hy)
        tl.go(*px((a, r)))
        step = 1 if b > a else -1
        passes = [(a, tl.t)]
        for c in range(a + step, b + step, step):
            passes.append((c, tl.step(px((c, r)))))
        ev["scrub"] = (r, passes, ev["start"], tl.t + 0.3)
        tl.hold(0.3)
    elif kind == "recover":
        # The cells it ate last come back in a wave; it watches from the lane
        # and has to eat them again.
        recent = [c for c in eaten if px(c) != (hx, hy)]    # not the one it stands on
        back = recent[-max(4, len(recent) // 4):]
        tl.go(hx, LANE_Y)
        t0 = tl.t + 0.2
        t1 = t0 + 0.1 * len(back)
        ev["recover"] = (list(reversed(back)), t0, t1)
        tl.hold(t1 + 0.6 - tl.t)
    else:
        tl.go(hx, LANE_Y)
        right = tile_x(len(ICONS) - 1) + TILE + 20
        left = tile_x(0) - 20
        if kind == "wall":
            loop = rng.randint(2, len(ICONS) - 2)     # the icon it circles
            tl.go(right + 2 * PITCH, LANE_Y)
            tl.go(right, LANE_Y)
            through_wall(tl, ev, right, up=True)
            y = BELOW
            for g in range(len(ICONS) - 1, 0, -1):      # gap between g-1 and g
                y = weave(tl, ev, g, y)
                if g == loop + 1:
                    # Round tile `loop`: over or under it to the gap on its
                    # other side, through, and back along its other face.
                    y = weave(tl, ev, g - 1, y)
                    y = weave(tl, ev, g, y)
            tl.go(left, y)
            t_down = through_wall(tl, ev, left, up=False)
            ev["bricks"].append((left, t_down, False))
            until = t_down + 0.6
        elif kind == "upgrade":
            # ceph orch upgrade: every daemon goes grey, waiting. It comes in
            # through the wall on the left and bumps each tile in turn, which
            # brings it back up, weaving over the row at two gaps on the way.
            # The version on the status line comes from releases.yml.
            ev["grey"] = ev["start"] + 0.2
            tl.go(left - 2 * PITCH, LANE_Y)
            tl.go(left, LANE_Y)
            through_wall(tl, ev, left, up=True)
            y, bumps = BELOW, []
            over = {rng.randint(1, 3), rng.randint(4, len(ICONS) - 2)}  # gaps it weaves through
            for i in range(len(ICONS)):
                xc = tile_x(i) + TILE / 2
                tl.go(xc, y)
                tl.go(xc, ROW_Y + TILE + 6 if y == BELOW else ROW_Y - 6)
                bumps.append(tl.t)
                tl.hold(0.1)
                tl.go(xc, y)
                if i + 1 in over:
                    y = weave(tl, ev, i + 1, y)
            ev["upgrade"] = bumps
            tl.go(right, y)
            t_down = through_wall(tl, ev, right, up=False)
            ev["bricks"].append((right, t_down, False))
            until = t_down + 0.6
        elif kind == "shatter":
            # Rams an icon, goes on through the hole, round a neighbour and
            # back down the same way; the icon mends once it has gone.
            i = rng.randrange(1, len(ICONS))
            xc = tile_x(i) + TILE / 2
            tl.go(xc + 2 * PITCH, LANE_Y)
            tl.go(xc, LANE_Y)
            through_wall(tl, ev, xc, up=True)
            tl.go(xc, ROW_Y + TILE + 6)
            hit = tl.t
            tl.hold(0.1)
            tl.go(xc, ABOVE)
            left = i >= len(ICONS) - 2 or (i >= 2 and rng.random() < 0.5)
            near, far = (i, i - 1) if left else (i + 1, i + 2)
            y = weave(tl, ev, far, ABOVE)       # over the neighbour, down its far side
            weave(tl, ev, near, y)              # back up between it and the hole
            ev["wobbles"] = [(g, t) for g, t in ev["wobbles"] if g != i]
            tl.go(xc, ABOVE)
            tl.go(xc, BELOW)
            down = through_wall(tl, ev, xc, up=False)
            ev["shatter"] = (i, hit, down + 0.4)
            until = down + 1.0                  # it watches the icon come back
        elif kind == "osd":
            # An icon goes dark and keels over; it nudges it back up.
            i = rng.randrange(1, len(ICONS))
            xc = tile_x(i) + TILE / 2
            tl.go(xc + 2 * PITCH, LANE_Y)
            tl.go(xc, LANE_Y)
            through_wall(tl, ev, xc, up=True)
            for _ in range(2):
                tl.go(xc, ROW_Y + TILE + 6)
                bump = tl.t
                tl.hold(0.1)
                tl.go(xc, BELOW)
                tl.hold(0.25)
            ev["osd"] = (i, ev["start"] - LEAD, bump, rng.randrange(OSDS))   # the tile, and its osd id
            tl.hold(0.4)
            through_wall(tl, ev, xc, up=False)
            until = tl.t
        else:                                   # octopus
            xc = tile_x(0) + TILE / 2
            tl.go(xc + 5 * PITCH, LANE_Y)
            ev["approach"] = tl.t
            tl.go(xc - (len(SEGMENTS) - 1) * PITCH, LANE_Y)
            grab = tl.t
            tips = [(x, y - DRAG) for x, y in (tl.H[-len(SEGMENTS)], tl.H[-len(SEGMENTS) + 1])]
            tl.hold(1.8, wiggle=True)
            ev["tentacles"] = (grab, grab + 1.8, tips, xc)
            ev["bricks"].append((xc, grab - 0.25, False))
            ev["bulge"] = (0, grab - 0.2)
            ev["wobbles"].append((0, grab + 0.9))
            # A fourth arm plucks the nearest uneaten top-row cell into the tile.
            prey = [c for c in active if c[1] == 0 and c not in eaten]
            if prey:
                cell = min(prey, key=lambda c: abs(px(c)[0] - xc))
                ev["steal"] = (cell, grab + 1.0)
            until = grab + 2.3
        tl.hold(until - tl.t)
    # Back to the meal: to where its tail was, then retrace into the old shape.
    ev["back"] = tl.t
    x0, y0 = shape[0]
    tl.go(x0, tl.head[1])
    tl.go(x0, y0)
    for point in shape[1:]:
        tl.step(point)
    ev["end"] = tl.t
    return ev


def peak(ev):
    """The moment worth looking at."""
    if "warn" in ev:
        return max(ev["start"], ev["warn"][2] - 1.0)
    if "shatter" in ev:
        return ev["shatter"][1]
    if "tentacles" in ev:
        return ev["tentacles"][0]
    if "osd" in ev:
        return ev["osd"][2] - 0.5
    if "scrub" in ev:
        return ev["scrub"][1][0][1]
    if "recover" in ev:
        return ev["recover"][1]
    if "upgrade" in ev:
        return ev["upgrade"][len(ICONS) // 2]
    return ev["bricks"][0][1]


def roll_kinds(rng, only):
    """The events of each meal: every kind once, never the same twice in a
    row; one meal gets a second one."""
    if only:
        return [[only] for _ in range(MEALS)]
    kinds = list(EVENTS) + [rng.choice(EVENTS) for _ in range(MEALS - len(EVENTS))]
    while True:
        rng.shuffle(kinds)
        if all(a != b for a, b in zip(kinds[:MEALS], kinds[1:MEALS])):
            break
    kinds, left = kinds[:MEALS], kinds[MEALS:]
    # A second event never recovers; swap one in if that is what was left over.
    if "recover" in left:
        i = kinds.index(rng.choice([k for k in kinds if k != "recover"]))
        kinds[i], left[left.index("recover")] = "recover", kinds[i]
    extra = left[0] if left else rng.choice([k for k in EVENTS if k != "recover"])
    per_meal = [[k] for k in kinds]
    n = rng.choice([i for i in range(MEALS) if kinds[i] not in ("recover", extra)
                    and (i + 1 >= MEALS or kinds[i + 1] != extra)])
    per_meal[n].append(extra)
    return per_meal


def cycle(active, seed, only=None):
    """The whole cycle as one timeline: MEALS meals, each interrupted by its
    events. A meal starts where the last one ended; only the last walks back
    to START so the cycle wraps. With no active cell the snake patrols the
    lane and nothing happens.

    Returns (timeline, events, meals, grid): meals are {start, lane, end,
    events}; grid maps a cell to its (time, "eat" | "refill") history."""
    rng = random.Random(seed)
    first, _ = plan(active)
    tl = Timeline(LOOP_SECONDS / (len(first) + COLS + 1))   # the first meal plus the walk home
    grid = {c: [] for c in active}
    events, meals = [], []
    pos = START
    for n, kinds in enumerate(roll_kinds(rng, only)):
        moves, eats = plan(active, pos)
        if not active:
            # Nothing to eat: it patrols the lane, end to end, and no event
            # can happen (every one needs a cell it ate).
            moves = walk(pos, (COLS - 1 if pos[0] < COLS // 2 else 0, LANE))
        meal = {"start": tl.t, "events": []}
        # Where each event interrupts: at a share of the cells eaten.
        shares = sorted(rng.uniform(*INTERRUPT) for _ in kinds)
        per_cell = sorted(k for k, cs in eats.items() for _ in cs)
        stops = {}
        for kind, share in zip(kinds if per_cell else [], shares):
            at = max(3, per_cell[int(share * (len(per_cell) - 1))])
            while at in stops:
                at += 5
            stops[at] = kind
        gone, k = [], 0
        while k < len(moves):
            t = tl.step(px(moves[k]))
            for c in eats.get(k, []):
                grid[c].append((t, "eat"))
                gone.append(c)
            if k in stops:
                ev = detour(stops[k], tl, rng, gone, active)
                events.append(ev)
                meal["events"].append(ev)
                if "steal" in ev:                   # the octopus took a cell
                    cell, t_steal = ev["steal"]
                    grid[cell].append((t_steal, "eat"))
                    for j in range(k + 1, len(moves)):
                        if cell in eats.get(j, []):
                            eats[j].remove(cell)
                if "recover" in ev:                 # cells came back: eat them again
                    back, t0, t1 = ev["recover"]
                    for c in back:
                        grid[c].append((t0 + (t1 - t0) * (back.index(c) / max(1, len(back) - 1)), "refill"))
                    left = {c for j in range(k + 1, len(moves)) for c in eats.get(j, [])} | set(back)
                    rest, rest_eats = plan({c: active[c] for c in left}, moves[k])
                    moves = moves[:k + 1] + rest
                    eats = {j: cs for j, cs in eats.items() if j <= k}
                    eats.update({k + 1 + j: cs for j, cs in rest_eats.items()})
                    stops = {j: kind for j, kind in stops.items() if j <= k}
            k += 1
        sweep = meal["lane"] = t + 0.3          # the grid backfills left to right
        pos = moves[-1]
        if n == MEALS - 1:
            for cell in walk(pos, (0, LANE)):
                tl.step(px(cell))
        tl.hold(max(DIGEST, sweep + 1.2 - tl.t))
        for c in grid:
            grid[c].append((sweep + (tl.t - REFILL - sweep) * c[0] / (COLS - 1), "refill"))
        meal["end"] = tl.t
        meals.append(meal)
    tl.close()
    return tl, events, meals, grid


# --- the scouts --------------------------------------------------------------
# Two small tentacles live in the Ceph tile: the scout and its smaller sibling,
# the kid. They creep out between events, alone or together. Each one's dots
# all follow its tip's keyframes, each LAG s further behind.

LAG = 0.07
CREEP, HURRY, BOLT = 70, 120, 220           # px/s
HOME = (tile_x(0) + TILE / 2, ROW_Y + TILE / 2)
UNDER = ROW_Y + TILE + 5                    # just under the icon row
OVER = ROW_Y - 8                            # a tip peeking over a tile
BOTTOM = Y0 + ROWS * PITCH + 4              # just under the grid, over the status line
SCOUTS = [                                  # name, dots, tip and root radius, home
    ("scout", 10, 2.5, 5.5, HOME),
    ("kid", 8, 2.0, 4.2, (HOME[0] + 9, HOME[1] + 4)),
]
LONG_WINDOW = 12.0                          # a quiet stretch this long gets two outings
ANTICIPATE = 5.0                            # a remark on an event may set off this early
CLEARANCE = 28                              # a tip out of the tile keeps this far from the head
SIGNS = {
    "cpp": ["c++26?", "modules?", "constexpr all?", "-Werror?"],
    "c": ["rewrite in rust?", "void*?", "malloc?", "k&r?"],
    "py": ["pip install ceph?", "3.14?", "asyncio?", "type hints?"],
    "bash": ["set -e?", "[[ or [?", "shellcheck?", "#!/bin/sh?"],
    "go": ["rewrite in go?", "err != nil?", "generics?", "goroutine?"],
    "openstack": ["cinder?", "nova?", "neutron?", "manila?", "cinder++"],
    "gcp": ["more zones?", "preemptible?", "egress bill?", "us-east1?"],
    "grid": ["pg_num 1024?", "scrub?", "backfill?", "1 pg stuck?"],
    "status": ["ceph -s?", "ceph -w?", "all clean?"],
    "peek": ["hi.", "psst.", "osd?", "hungry?", "slow down."],
    "top": ["nice view.", "all up.", f"{OSDS} osds.", "anyone?"],
    "busy": ["busy week.", "streak?", "commits?"],
    "quiet": ["quiet week.", "holiday?", "nothing?"],
    "answer": ["no.", "nope.", "why?", "later.", "meh.", "yes?", "ask the snake.", "vampire."],
    # Releases: replaced at build time by release_signs(); this is the
    # fallback when releases.yml cannot be fetched.
    "ceph": ["tentacle?", "umbrella next?", "squid -> EOL", "reef? old.", "quincy who?",
             "infernalis?", "upgrade?", "ceph orch upgrade?", "pacific. rip."],
    "blood": ["blood?", "bite?", "neck?"],
    "garlic": ["garlic.", "garlic!", "no. garlic."],
    "boo": ["boo.", "found you.", "gotcha."],
    "brick": ["yours.", "take it.", "heavy."],
    "sorry": ["sorry.", "mine.", "tasty."],
    "after": ["again?", "told you.", "noted."],
    # Remarks on an event, from a safe spot, at its peak.
    "shatter": ["oops.", "ouch.", "mind the osd."],
    "osd": ["wake up.", "kick it.", "osd down?"],
    "wall": ["my wall.", "not again.", "bricks."],
    "health": ["uh oh.", "inconsistent.", "scrub it."],
    "scrub": ["deep scrub.", "all clean?", "slow."],
    "recover": ["backfill.", "objects/s.", "again."],
    "upgrade": ["upgrading.", "no downtime?", "orch upgrade.", "reboot?", "bump it."],
}
SEASONAL = {                                    # (weekday, month): extra signs
    (0, None): ["coffee?", "monday."], (4, None): ["friday deploy?"],
    (None, 1): ["new year?"], (None, 10): ["pumpkin?"], (None, 12): ["freeze?", "snow?"],
}


def seed_day(seed):
    """The day of the seed (a UTC hour), or today."""
    try:
        return datetime.date.fromisoformat(seed[:10])
    except ValueError:
        return datetime.datetime.now(datetime.timezone.utc).date()


def seasonal_signs(seed):
    """Extra peek/grid signs for the day of the seed."""
    day = seed_day(seed)
    out = []
    for (weekday, month), signs in SEASONAL.items():
        if (weekday is None or day.weekday() == weekday) and (month is None or day.month == month):
            out += signs
    return out


class Creep:
    """Tip keyframes (t, x, y) of one scout, plus its signs, brick nudges and
    the bricks it carried (brick, [(t, dx, dy), ...] of the brick's path)."""

    def __init__(self, t, home=HOME):
        self.home = home
        self.points = [(t, *home)]
        self.signs, self.nudges, self.steals = [], [], []
        self.capes = []                         # (from, until) it wears the vampire cape

    @property
    def t(self):
        return self.points[-1][0]

    @property
    def t0(self):
        return self.points[0][0]

    @property
    def pos(self):
        return self.points[-1][1:]

    def move(self, x, y, speed=CREEP):
        x0, y0 = self.pos
        self.points.append((self.t + math.hypot(x - x0, y - y0) / speed, x, y))

    def hold(self, seconds):
        if seconds > 0:
            self.points.append((self.t + seconds, *self.pos))

    def wait_for(self, t):
        self.hold(t - self.t)

    def say(self, text, seconds=1.5, side="up"):
        self.signs.append((self.t, seconds, *self.pos, text, side))
        self.hold(seconds)

    def vanish(self):
        """Back home in a blink; only used once the tip is off the canvas."""
        self.points.append((self.t + 0.01, *self.home))

    def carry(self, brick, bx):
        """Start carrying a brick: its path follows this scout's next moves."""
        self.steals.append((brick, [(self.t, 0.0, 0.0)]))
        self._bx = bx

    def drop(self):
        """The brick is where the scout is now."""
        brick, path = self.steals[-1]
        x, y = self.pos
        path.append((self.t, x - (self._bx + BRICK / 2), y - WALL_Y))

    def shift(self, delta):
        self.points = [(t + delta, x, y) for t, x, y in self.points]
        self.signs = [(t + delta, *rest) for t, *rest in self.signs]
        self.nudges = [(b, t + delta) for b, t in self.nudges]
        self.steals = [(b, [(t + delta, dx, dy) for t, dx, dy in path]) for b, path in self.steals]
        self.capes = [(a + delta, b + delta) for a, b in self.capes]

    def extend(self, other):
        self.points += other.points
        self.signs += other.signs
        self.nudges += other.nudges
        self.steals += other.steals
        self.capes += other.capes

    def sort(self):
        """Outings are placed out of order; put the keyframes in order and
        make sure none overlap."""
        self.points.sort()
        self.signs.sort()
        for (t0, *_), (t1, *_) in zip(self.points, self.points[1:]):
            assert t1 >= t0
        self.points = [p for i, p in enumerate(self.points) if i == 0 or p[0] > self.points[i - 1][0]]


def snake_near(tl, t0, t1, x, y, r):
    """First time in [t0, t1] the snake's head is within r of (x, y)."""
    for t, m, _ in tl.frames:
        if t0 <= t <= t1:
            hx, hy = tl.H[m % len(tl.H)]
            if math.hypot(hx - x, hy - y) < r:
                return t
    return None


def clear_of_snake(tl, cr, r=CLEARANCE):
    """True if the snake's head never comes within r of the tip while it is
    out of the tile."""
    pts = cr.points
    i = 0
    for t, m, _ in tl.frames:
        if t < pts[0][0] or t > pts[-1][0]:
            continue
        while pts[i + 1][0] < t:
            i += 1
        (t0, x0, y0), (t1, x1, y1) = pts[i], pts[i + 1]
        f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
        x, y = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
        if tile_x(0) <= x <= tile_x(0) + TILE and ROW_Y <= y <= ROW_Y + TILE:
            continue
        hx, hy = tl.H[m % len(tl.H)]
        if math.hypot(hx - x, hy - y) < r:
            return False
    return True


def creep_out(cr):
    cr.move(cr.home[0], UNDER)


def creep_home(cr, via_lane=False):
    if via_lane:
        cr.move(cr.home[0], LANE_Y, HURRY)
    cr.move(cr.home[0], UNDER, HURRY)
    cr.move(*cr.home, HURRY)


def tile_cx(j):
    return tile_x(j) + TILE / 2


def gap_x(g):
    """The gap between tiles g-1 and g."""
    return tile_x(g) - TGAP / 2


def question(rng, signs, j):
    """Something to ask over tile j: about it, or about Ceph releases."""
    return rng.choice(signs[ICONS[j]] if rng.random() < 0.7 else signs["ceph"])


def behind(cr, j, speed=CREEP):
    """Along under the row and up behind tile j."""
    cr.move(tile_cx(j), UNDER, speed)
    cr.move(tile_cx(j), HOME[1], speed)


def down_and_home(cr, j):
    cr.move(tile_cx(j), HOME[1], HURRY)
    cr.hold(0.3)
    cr.move(tile_cx(j), UNDER, HURRY)
    creep_home(cr)


# Solo routes: (creep, rng, signs, ctx). The scheduler keeps every outing
# clear of the snake, so routes may go anywhere.

def route_icon(cr, rng, signs, ctx):
    """Hides behind another tile, then peeks over its top with a question."""
    j = rng.randint(1, len(ICONS) - 1)
    creep_out(cr)
    behind(cr, j)
    cr.hold(0.6)
    cr.move(tile_cx(j), OVER)
    cr.say(question(rng, signs, j), side="right")
    down_and_home(cr, j)


def route_top(cr, rng, signs, ctx):
    """Up a gap, along the top of the icon row over a few tiles, down the far gap."""
    a = rng.randint(1, len(ICONS) - 3)
    b = min(len(ICONS) - 1, a + rng.randint(2, 3))
    creep_out(cr)
    cr.move(gap_x(a), UNDER)
    cr.move(gap_x(a), OVER)
    mid = rng.randint(a, b - 1)
    cr.move(tile_cx(mid), OVER - 2)
    cr.say(rng.choice(signs["top"]), side="right")
    cr.move(gap_x(b), OVER - 2)
    cr.move(gap_x(b), UNDER, HURRY)
    creep_home(cr)


def route_grid(cr, rng, signs, ctx):
    """Pokes a top-row cell."""
    col = rng.randint(2, COLS - 3)
    x, y = px((col, 0))
    creep_out(cr)
    cr.move(cr.home[0], LANE_Y)
    cr.move(x, LANE_Y)
    cr.move(x, y - CELL / 2 - 3)
    cr.say(rng.choice(signs["grid"]))
    cr.move(x, LANE_Y, HURRY)
    creep_home(cr, via_lane=True)


def route_status(cr, rng, signs, ctx, pool="status"):
    """Down the left margin to the status line; leaves by the bottom edge."""
    edge = X0 - 10
    creep_out(cr)
    cr.move(cr.home[0], LANE_Y)
    cr.move(edge, LANE_Y, HURRY)
    cr.move(edge, STATUS_Y - 3, HURRY)
    cr.move(X0 + 200, STATUS_Y - 3, HURRY)
    cr.move(X0 + 290, STATUS_Y - 3)
    if pool == "status" and rng.random() < 0.5:
        pool = "ceph"
    cr.say(rng.choice(signs[pool]), side="right")
    cr.move(X0 + 290, HEIGHT + 12, HURRY)
    cr.vanish()


def route_bottom(cr, rng, signs, ctx):
    """Down the left margin and along under the grid to the busiest column
    (or an empty one), with a word about it; leaves by the right edge."""
    active = ctx["active"]
    weight = {c: sum(lvl for (col, _), lvl in active.items() if col == c) for c in range(2, COLS - 2)}
    empty = [c for c, w in weight.items() if w == 0]
    if empty and (len(empty) == len(weight) or rng.random() < 0.5):
        col, pool = rng.choice(empty), "quiet"
    else:
        col, pool = max(weight, key=weight.get), "busy"
    x = px((col, 0))[0]
    edge = X0 - 10
    creep_out(cr)
    cr.move(cr.home[0], LANE_Y)
    cr.move(edge, LANE_Y, HURRY)
    cr.move(edge, BOTTOM, HURRY)
    cr.move(max(edge, x - 60), BOTTOM, HURRY)
    cr.move(x, BOTTOM)
    cr.say(rng.choice(signs[pool]), side="right")
    cr.move(WIDTH + 12, BOTTOM, HURRY)
    cr.vanish()


def route_wall(cr, rng, signs, ctx):
    """Nudges a brick under the icons twice; sometimes takes it home."""
    xs = brick_xs()
    b = rng.randint(brick_at(tile_x(1)), brick_at(tile_x(len(ICONS) - 1) + TILE))
    creep_out(cr)
    cr.move(xs[b] + BRICK / 2, UNDER)
    cr.move(xs[b] + BRICK / 2, WALL_Y - 4)
    for _ in range(2):
        cr.nudges.append((b, cr.t))
        cr.hold(0.5)
    if rng.random() < 0.5:
        cr.carry(b, xs[b])                      # the brick follows it home
        cr.move(*cr.home, HURRY)
        cr.drop()
        return
    cr.move(xs[b] + BRICK / 2, UNDER, HURRY)
    creep_home(cr)


def route_peek(cr, rng, signs, ctx):
    cr.move(cr.home[0], UNDER + 4)
    cr.say(rng.choice(signs["peek" if rng.random() < 0.5 else "ceph"]), side="right")
    cr.move(*cr.home, HURRY)


def route_after(cr, rng, signs, ctx):
    """To the status line after an alarm, with a remark."""
    route_status(cr, rng, signs, ctx, "after")


ROUTES = [route_icon, route_top, route_grid, route_status, route_bottom, route_wall]


# Duets: (a, b, rng, signs, ctx), both starting at the same time.

def duet_icons(a, b, rng, signs, ctx):
    """One asks over a tile; the other answers over the next one, once the
    question is gone."""
    j = rng.randint(1, len(ICONS) - 2)
    k = j + 1
    creep_out(a)
    behind(a, j)
    creep_out(b)
    behind(b, k)
    ready = max(a.t, b.t) + 0.5
    a.wait_for(ready)
    a.move(tile_cx(j), OVER)
    a.say(question(rng, signs, j), side="right")
    a.move(tile_cx(j), HOME[1], HURRY)
    b.wait_for(a.t + 0.1)
    b.move(tile_cx(k), OVER)
    b.say(rng.choice(signs["answer"]), 1.2, side="right")
    a.wait_for(b.t)
    down_and_home(a, j)
    b.move(tile_cx(k), HOME[1], HURRY)
    b.hold(0.6)
    b.move(tile_cx(k), UNDER, HURRY)
    creep_home(b)


def duet_hide(a, b, rng, signs, ctx):
    """Peek-a-boo: a hides behind a tile; b looks under each tile on the way;
    a pops over the top, b bolts home."""
    j = rng.randint(1, 5)
    creep_out(a)
    behind(a, j)
    creep_out(b)
    b.wait_for(a.t + 0.4)
    for g in range(1, j + 1):
        b.move(tile_cx(g), UNDER)
        b.hold(0.35)
    a.wait_for(b.t)
    a.move(tile_cx(j) - 8, OVER, HURRY)
    a.say(rng.choice(signs["boo"]), 1.0, side="right")
    b.wait_for(a.signs[-1][0] + 0.15)
    b.say("!", 0.3, side="right")
    b.move(*b.home, BOLT)
    a.move(tile_cx(j), HOME[1], HURRY)
    a.hold(0.3)
    a.move(tile_cx(j), UNDER, HURRY)
    creep_home(a)


def duet_brick(a, b, rng, signs, ctx):
    """a works a brick loose and drags it halfway; b carries it the rest of
    the way home."""
    xs = brick_xs()
    brick = rng.randint(brick_at(tile_x(2)), brick_at(tile_x(len(ICONS) - 2) + TILE))
    bx = xs[brick] + BRICK / 2
    creep_out(a)
    a.move(bx, UNDER)
    a.move(bx, WALL_Y - 4)
    for _ in range(2):
        a.nudges.append((brick, a.t))
        a.hold(0.5)
    mx = (a.home[0] + bx) / 2
    a.carry(brick, xs[brick])
    a.move(mx, UNDER + 2)
    a.drop()
    creep_out(b)
    b.move(mx - 14, UNDER + 2)
    b.wait_for(a.t + 0.3)
    a.wait_for(b.t)
    a.say(rng.choice(signs["brick"]), 1.0, side="right")
    a.drop()
    a.move(*a.home, HURRY)
    b.wait_for(a.t)
    b.move(*b.home, HURRY)
    a.steals[-1][1].append((b.t, b.home[0] - bx, b.home[1] - WALL_Y))


def duet_garlic(kid, scout, rng, signs, ctx):
    """The kid, in a cape, peeks over a tile asking for blood; the scout
    answers from the next tile; the kid bolts."""
    j = rng.randint(1, len(ICONS) - 2)
    k = j + 1
    cape_on = kid.t + 0.1
    creep_out(kid)
    behind(kid, j)
    creep_out(scout)
    behind(scout, k)
    kid.wait_for(max(kid.t, scout.t) + 0.5)
    kid.move(tile_cx(j), OVER)
    kid.say(rng.choice(signs["blood"]), side="right")
    scout.wait_for(kid.t + 0.1)
    scout.move(tile_cx(k), OVER)
    scout.say(rng.choice(signs["garlic"]), 1.2, side="right")
    kid.wait_for(scout.signs[-1][0] + 0.4)
    kid.say("!", 0.3, side="right")
    kid.move(*kid.home, BOLT)
    kid.capes.append((cape_on, kid.t))
    scout.hold(0.4)
    down_and_home(scout, k)


duet_garlic.order = [1, 0]                      # the kid is always the vampire
DUETS = [duet_icons, duet_hide, duet_brick, duet_garlic]


def brick_xs():
    count = int((WIDTH - 2 * X0 + BRICK_GAP) / (BRICK + BRICK_GAP))
    return [X0 + b * (BRICK + BRICK_GAP) for b in range(count)]


def brick_at(x):
    """Index of the brick nearest x."""
    xs = brick_xs()
    return xs.index(min(xs, key=lambda v: abs(v - x)))


def comment(cr, rng, signs, ev, tl):
    """A remark on an event at its peak: for shatter and OSD-down from over a
    tile well away from the one hit, otherwise from under the Ceph tile.
    Returns False if it cannot be fitted into the event."""
    kind = ev["kind"]
    at = peak(ev) + (0.3 if kind == "shatter" else 0.0)
    if kind == "wall":
        at = ev["bricks"][0][1]
    if kind in ("shatter", "osd", "upgrade"):
        # Over a tile well away from the one hit (or, in an upgrade, from
        # the middle one the snake is bumping at the peak).
        i = ev[kind][0] if kind != "upgrade" else len(ICONS) // 2
        j = rng.choice([j for j in range(1, len(ICONS)) if abs(j - i) >= 3])
        creep_out(cr)
        behind(cr, j)
        cr.hold(0.4)
        cr.move(tile_cx(j), OVER, HURRY)
        lead = cr.t - cr.t0
        cr.say(rng.choice(signs[kind]), side="right")
        down_and_home(cr, j)
    else:
        cr.move(cr.home[0], UNDER + 4)
        lead = cr.t - cr.t0
        cr.say(rng.choice(signs[kind]), side="right")
        cr.move(*cr.home, HURRY)
    cr.shift(at - lead - cr.t0)
    if cr.t0 < ev["start"] - ANTICIPATE or cr.t > ev["end"] + 2.0:
        return False
    return snake_near(tl, cr.t0, cr.t, *cr.signs[0][2:4], 70) is None


def scouts(tl, events, meals, seed, active, releases=None):
    """Keyframes of both scouts. In every quiet stretch of a meal (before the
    first event, between events, after the last) one of them goes out, or
    both for a long one; once a meal they go together. Each event gets a
    remark from a safe spot. During the octopus event the scout is the
    lookout that bolts before the grab and the kid stays in. After an alarm
    one of them goes to read the status line."""
    rng = random.Random(f"{seed}/scout")
    extra = seasonal_signs(seed)
    signs = {k: v + (extra if k in ("peek", "grid") else []) for k, v in SIGNS.items()}
    if releases is not None:
        signs["ceph"] = release_signs(releases, seed_day(seed))
    ctx = {"active": active}
    crs = [Creep(0.0, home) for *_, home in SCOUTS]
    used = [{r: 0 for r in ROUTES} for _ in SCOUTS]
    duets = {d: 0 for d in DUETS}
    stolen, said = set(), []

    def apart(trials):
        """No sign while another sign is up (0.4 s clear), and no brick that
        was already carried off."""
        return (all(t + s + 0.4 <= a or t >= b + 0.4
                    for tr in trials for t, s, *_ in tr.signs for a, b in said)
                and not any(b in stolen for tr in trials for b, _ in tr.nudges + tr.steals))

    def accept(pairs):
        for who, trial in pairs:
            said.extend((t, t + s) for t, s, *_ in trial.signs)
            stolen.update(b for b, _ in trial.steals)
            crs[who].extend(trial)

    def place(free, who, maker, skip_first=False):
        """Try to fit the trials made by maker(t) into one of the free
        intervals at a random offset; on success split the interval and
        return True."""
        for i in sorted(range(int(skip_first), len(free)), key=lambda _: rng.random()):
            a, b = free[i]
            for _ in range(8):                  # the route is random: another tile, cell, brick
                trials = maker(a)
                span = max(tr.t for tr in trials) - a
                if span > b - a:
                    continue
                delta = rng.uniform(0, b - a - span)
                for tr in trials:
                    tr.shift(delta)
                if not apart(trials) or not all(clear_of_snake(tl, tr) for tr in trials):
                    continue
                accept(list(zip(who, trials)))
                free[i:i + 1] = [(a, a + delta - 0.5), (a + delta + span + 0.5, b)]
                return True
        return False

    def solo(route, who):
        def maker(t):
            tr = Creep(t, crs[who].home)
            route(tr, random.Random(rng.random()), signs, ctx)
            return [tr]
        return maker

    def duet(d, order):
        def maker(t):
            a, b = (Creep(t, crs[w].home) for w in order)
            d(a, b, random.Random(rng.random()), signs, ctx)
            return [a, b]
        return maker

    for meal in meals:
        evs = meal["events"]
        octo = next((ev for ev in evs if ev["kind"] == "octopus"), None)
        avail = [0, 1]
        if octo:
            # The lookout: out under the tile, "!" as the snake gets close,
            # home before the arms strike. On a dense grid the snake is quick
            # (small dt), so it sets off early; if even that is too late it
            # stays in and only says sorry afterwards.
            grab = octo["tentacles"][0]
            trial = Creep(min(octo["start"], grab - 1.3))
            trial.move(HOME[0], UNDER + 12)
            near = snake_near(tl, trial.t, grab, *trial.pos, 70) or octo["approach"]
            trial.hold(max(0.0, near - trial.t))
            trial.say("!", 0.3, side="right")
            trial.move(*HOME, BOLT)
            if trial.t >= grab:
                trial = Creep(octo["start"])
            trial.points.append((octo["end"] + 1.0, *HOME))
            trial.move(HOME[0], UNDER + 4)
            trial.say(rng.choice(signs["sorry"]), side="right")
            trial.move(*HOME, HURRY)
            accept([(0, trial)])
            avail = [1]
        # Quiet stretches: before the first event, between events, after the
        # last (the snake waits on the lane through the backfill).
        edges = ([meal["start"] + 1.5] + [t for ev in evs for t in (ev["start"] - 0.5, ev["end"] + 1.0)]
                 + [min(meal["end"] - 0.5, tl.t - 1.5)])
        free = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
        for ev in evs:
            if ev["kind"] == "octopus":
                continue
            who = rng.choice(avail)
            trial = Creep(ev["start"], crs[who].home)
            if comment(trial, random.Random(rng.random()), signs, ev, tl) and apart([trial]):
                accept([(who, trial)])
                free = [w for a, b in free                 # it may set off before the event
                        for w in ((a, min(b, trial.t0 - 0.5)), (max(a, trial.t + 0.5), b)) if w[1] > w[0]]
        if any(ev["kind"] in ("health", "osd") for ev in evs):
            # After an alarm one of them would rather go and read the status line.
            who = rng.choice(avail)
            place(free, [who], solo(route_after, who), skip_first=True)
        if len(avail) == 2:
            for d in sorted(DUETS, key=lambda d: (duets[d], rng.random())):
                order = getattr(d, "order", None) or ([0, 1] if rng.random() < 0.5 else [1, 0])
                if place(free, order, duet(d, order)):
                    duets[d] += 1
                    break
        # One solo outing per stretch, a second in a long one; the scouts take
        # turns and each prefers the routes it has used least.
        who = rng.choice(avail)
        for a, b in sorted(free, key=lambda w: w[0]):
            window = [(a, b)]
            for n in range(2):
                if n and max((q - p for p, q in window), default=0) < LONG_WINDOW:
                    break
                routes = sorted(ROUTES, key=lambda r: (used[who][r], rng.random()))
                if n == 0:
                    routes.append(route_peek)   # the short one, if nothing else fits
                for route in routes:
                    if place(window, [who], solo(route, who)):
                        used[who][route] = used[who].get(route, 0) + 1
                        break
                who = avail[(avail.index(who) + 1) % len(avail)]
    for cr in crs:
        cr.sort()
    return crs


# --- CSS keyframes -----------------------------------------------------------

class Css:
    def __init__(self, period):
        self.T = period
        self.digits = max(2, math.ceil(math.log10(period / 0.3)))  # ~3 ms steps
        self.rules = []
        self.defs = []      # clip paths created alongside the animations
        self.cache = {}

    def pct(self, t):
        t = max(0.0, min(100.0, 100 * t / self.T))
        return f"{t:.{self.digits}f}".rstrip("0").rstrip(".") + "%"

    def animate(self, stops, extra=""):
        """stops: [(t, 'prop:value;...')] within the cycle; returns a class name.
        Offsets with the same body share one block (`0%,4.9%{...}`), which
        halves the file: most stops are a rest state. Of stops that land on
        the same offset the last one wins, as CSS would have it anyway."""
        at = {}
        for t, props in sorted(stops, key=lambda s: s[0]):
            at[self.pct(t)] = props
        offsets = {}
        for pct, props in at.items():
            offsets.setdefault(props, []).append(pct)
        body = "".join(f"{','.join(pcts)}{{{props}}}" for props, pcts in offsets.items())
        if (body, extra) not in self.cache:
            name = f"a{len(self.cache) + 1}"
            self.rules.append(f"@keyframes {name}{{{body}}}"
                              f".{name}{{animation:{name} {self.T:.3f}s linear infinite;{extra}}}")
            self.cache[body, extra] = name
        return self.cache[body, extra]

    def episode(self, rest, stops):
        """Rest state, with episodes of stops in between."""
        return self.animate([(0, rest)] + list(stops) + [(self.T, rest)])

    def windows(self, inside, outside, spans):
        """Toggle between two states at the edges of the given spans. Spans
        that touch or overlap are one: otherwise the outside state would
        show for a frame between them."""
        merged = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] + 0.05:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        stops = []
        for a, b in merged:
            stops += [(a, outside), (a + 0.01, inside), (b - 0.01, inside), (b, outside)]
        return self.episode(outside, stops)


BOX = "transform-box:fill-box;transform-origin:center"


def merge_stops(stops, rest):
    """Fill properties missing from a stop with the rest state's values."""
    defaults = dict(p.split(":", 1) for p in rest.split(";"))
    out = []
    for t, props in sorted(stops, key=lambda s: s[0]):
        values = dict(defaults)
        values.update(p.split(":", 1) for p in props.split(";"))
        out.append((t, ";".join(f"{k}:{v}" for k, v in values.items())))
    return out


def snake_parts(css, tl):
    """The snake's segments, tail first so the head is on top."""
    out = []
    for i in reversed(range(len(SEGMENTS))):
        size = SEGMENTS[i]
        stops = [(t, f"transform:translate({num(x)}px,{num(y)}px)")
                 for t, x, y in simplify(tl.segment(i))]
        body = (f'<rect x="{-size / 2}" y="{-size / 2}" width="{size}" height="{size}" '
                f'rx="{size / 4:.1f}" fill="{SNAKE}"/>')
        out.append(f'<g class="{css.animate(stops)}">{body}</g>')
    return "".join(out)


def shards(rng):
    """The tile cut into irregular pieces: a jittered 3x3 grid, some cells
    split in two. Polygons in tile coordinates."""
    n = 3
    s = TILE / n
    pts = [[(c * s + (rng.uniform(-7, 7) if 0 < c < n else 0),
             r * s + (rng.uniform(-7, 7) if 0 < r < n else 0))
            for c in range(n + 1)] for r in range(n + 1)]
    out = []
    for r in range(n):
        for c in range(n):
            a, b, d, e = pts[r][c], pts[r][c + 1], pts[r + 1][c + 1], pts[r + 1][c]
            if rng.random() < 0.5:
                out += [[a, b, d], [a, d, e]] if rng.random() < 0.5 else [[a, b, e], [b, d, e]]
            else:
                out.append([a, b, d, e])
    return out


def shatter_pieces(css, name, j, x, t0, t1, rng):
    """The tile in pieces, flung out from where the snake hits (bottom
    centre); visible only while it is broken."""
    out = []
    for k, poly in enumerate(shards(rng)):
        cid = f"clip-{name}-{j}-{k}"
        points = " ".join(f"{x + px_:.1f},{ROW_Y + py_:.1f}" for px_, py_ in poly)
        css.defs.append(f'<clipPath id="{cid}"><polygon points="{points}"/></clipPath>')
        cx = sum(p[0] for p in poly) / len(poly) - TILE / 2
        cy = sum(p[1] for p in poly) / len(poly) - TILE
        dx = cx * 2.0 + (12 if cx >= 0 else -12) + rng.uniform(-6, 6)
        dy = cy * 0.4 - rng.uniform(4, 14)
        fall = rng.uniform(40, 70)
        rot = rng.uniform(-160, 160)
        hidden = "transform:translate(0,0) rotate(0);opacity:0"

        def at(fx, fy, deg):
            return f"transform:translate({fx:.1f}px,{fy:.1f}px) rotate({deg:.0f}deg);opacity:1"
        landed = at(dx * 1.4, fall, rot)
        cls = css.episode(hidden, [
            (t0, hidden),
            (t0 + 0.01, at(0, 0, 0)),
            (t0 + 0.3, at(dx, dy, rot / 2)),
            (t0 + 0.9, landed),
            (t0 + 1.1, at(dx * 1.45, fall - rng.uniform(8, 16), rot + 20)),   # bounce
            (t0 + 1.3, landed),
            (t1 - 0.5, landed),
            (t1 - 0.05, at(0, 0, 0)),
            (t1 + 0.01, hidden),
        ])
        out.append(f'<g class="{cls}" style="{BOX}"><g clip-path="url(#{cid})">'
                   f'<use href="#tile-{name}" x="{x}" y="{ROW_Y}" width="{TILE}" height="{TILE}"/></g></g>')
    return "".join(out)


def draw_tentacles(css, grab, release, tips, root, plans=None):
    out = []
    plans = plans or [(root - 9, tips[0], 1, 5), (root + 1, tips[0], -1, 4), (root - 4, tips[1], 1, 3.5)]
    for k, (x0, (tx, ty), bend, width) in enumerate(plans):
        y0 = ROW_Y + TILE - 4
        # S-shaped reach that curls round the segment at the tip.
        d = (f"M{x0:.1f} {y0:.1f}C{x0 + 14 * bend:.1f} {y0 + 14:.1f} {tx - 16 * bend:.1f} {ty - 22:.1f} "
             f"{tx + 3 * bend:.1f} {ty - 8:.1f}q{7 * bend:.1f} 6 {1 * bend:.1f} 14")
        length = int(2 * math.hypot(tx - x0, ty - y0) + 80)   # longer than the path
        lag = 0.08 * k
        shown, hidden = "stroke-dashoffset:0", f"stroke-dashoffset:{length}"
        cls = css.episode(hidden, [
            (grab - 0.45 + lag, hidden), (grab + lag, shown),
            (release, shown), (release + 0.5, hidden)])
        out.append(f'<path class="{cls}" d="{d}" stroke="{SNAKE}" stroke-width="{width}" '
                   f'stroke-linecap="round" stroke-dasharray="{length}" '
                   f'stroke-dashoffset="{length}" fill="none"/>')
    return "".join(out)


def draw_ink(css, release, root, colour, rng):
    """A puff of ink from under the tile as the tentacles let go."""
    out = []
    y = ROW_Y + TILE - 2
    hidden = "transform:translate(0,0) scale(0.2);opacity:0"
    for k in range(4):
        dx, dy = rng.uniform(-18, 18), rng.uniform(6, 22)
        t = release - 0.1 + 0.05 * k
        cls = css.episode(hidden, [
            (t, hidden),
            (t + 0.01, "transform:translate(0,0) scale(0.3);opacity:0.8"),
            (t + 0.35, f"transform:translate({dx * 0.7:.1f}px,{dy * 0.7:.1f}px) scale(1);opacity:0.5"),
            (t + 0.8, f"transform:translate({dx:.1f}px,{dy:.1f}px) scale(1.6);opacity:0"),
        ])
        out.append(f'<circle class="{cls}" style="{BOX}" cx="{root + rng.uniform(-6, 6):.1f}" '
                   f'cy="{y}" r="{rng.uniform(5, 8):.1f}" fill="{colour}" opacity="0"/>')
    return "".join(out)


# --- build -------------------------------------------------------------------

def build(cells, theme, seed, only=None, releases=None):
    pal = THEMES[theme]
    active = {cell: lvl for cell, lvl in cells.items() if lvl}
    tl, events, meals, grid = cycle(active, seed, only)
    crs = scouts(tl, events, meals, seed, active, releases)
    T = tl.t
    css = Css(T)
    rng = random.Random(f"{seed}/render")

    bricks, wobbles, shatters, tentacles, alarms = [], {}, [], [], []
    downs, bulges, scrubs, drags, steals, upgrades = {}, {}, [], [], [], []
    current = current_release(releases or [], seed_day(seed))
    version = current["version"] if current else SIGNS["ceph"][0].rstrip("?")
    for n, ev in enumerate(events):
        bricks += [(x, t, up, n) for x, t, up in ev["bricks"]]
        for i, t in ev["wobbles"]:
            wobbles.setdefault(i, []).append(t)
        if "shatter" in ev:
            shatters.append(ev["shatter"])
        if "tentacles" in ev:
            tentacles.append(ev["tentacles"])
            drags.append(ev["tentacles"][:2])
            bulges.setdefault(ev["bulge"][0], []).append(ev["bulge"][1])
            if "steal" in ev:
                steals.append((*ev["steal"], ev["tentacles"][3]))
        if "warn" in ev:
            (c, r), alarm, fix = ev["warn"]
            alarms.append((f"HEALTH_WARN 1 pgs inconsistent; pg {r + 1}.{c:x}", alarm, fix + 0.25, pal["warn"]))
        if "osd" in ev:
            i, down, fix, osd = ev["osd"]
            downs.setdefault(i, []).append((down, fix))
            alarms.append((f"HEALTH_WARN 1 osds down; osd.{osd}", down, fix + 0.3, pal["warn"]))
        if "scrub" in ev:
            scrubs.append(ev["scrub"])
            r, _, a, b = ev["scrub"]
            alarms.append((f"HEALTH_OK 1 pgs deep-scrubbing; pg {r + 1}.0", a, b, pal["ok"]))
        if "recover" in ev:
            back, t0, t1 = ev["recover"]
            alarms.append((f"HEALTH_WARN 1 pgs recovering; {len(back) * 37} objects/s",
                           t0 - LEAD, t1 + 0.5, pal["warn"]))
        if "upgrade" in ev:
            grey, bumps, end = ev["grey"], ev["upgrade"], ev["back"]
            upgrades.append((grey, bumps, end))
            n = len(ICONS)
            head = f"Upgrade to {version} ["
            # One line for the whole event; the bar and the count are
            # characters laid over it (leading spaces, same monospace font),
            # each fading into the next, so nothing in the line jumps.
            alarms.append((f"{head}{' ' * n}]  /{n} daemons upgraded", grey, end, pal["ok"]))
            for i, up in enumerate(bumps):
                pad = " " * (len(head) + i)
                alarms.append((pad + ".", grey, up + 0.01, pal["muted"]))
                alarms.append((pad + "=", up, end, pal["ok"]))
            pad = " " * (len(head) + n + 2)
            for k in range(n + 1):
                a = grey if k == 0 else bumps[k - 1]
                b = end if k == n else bumps[k] + 0.01
                alarms.append((pad + str(k), a, b, pal["ok"]))

    parts = []

    # Icons: drawn over the snake and the scout, which hide behind them.
    icons = []
    rest = "transform:rotate(0) scale(1);opacity:1;filter:grayscale(0)"
    GREY = "transform:rotate(0) scale(1);opacity:0.5;filter:grayscale(1)"
    for i, name in enumerate(ICONS):
        x = tile_x(i)
        use = f'<use href="#tile-{name}" x="{x}" y="{ROW_Y}" width="{TILE}" height="{TILE}"/>'
        stops = []
        for t in wobbles.get(i, []):
            stops += [(t + dt, f"transform:rotate({deg}deg) scale(1)")
                      for dt, deg in ((0, 0), (0.1, 9), (0.25, -6), (0.4, 3), (0.55, 0))]
        for t in bulges.get(i, []):                 # the octopus stirs inside
            stops += [(t + dt, f"transform:rotate(0) scale({s})")
                      for dt, s in ((0, 1), (0.15, 1.1), (0.4, 0.97), (0.6, 1))]
        for down, fix in downs.get(i, []):          # keels over, grey; nudged back up
            stops += [(down, "transform:rotate(0) scale(1);opacity:1;filter:grayscale(0)"),
                      (down + 0.35, "transform:rotate(14deg) scale(1);opacity:0.5;filter:grayscale(1)"),
                      (fix, "transform:rotate(14deg) scale(1);opacity:0.5;filter:grayscale(1)"),
                      (fix + 0.15, "transform:rotate(-5deg) scale(1);opacity:1;filter:grayscale(0)"),
                      (fix + 0.3, "transform:rotate(0) scale(1);opacity:1;filter:grayscale(0)")]
        for j, (tile, t0, t1) in enumerate(shatters):
            if tile == i:
                # Gone while the pieces are out; flickers as it comes back.
                stops += [(t0, "opacity:1"), (t0 + 0.01, "opacity:0"), (t1, "opacity:0"),
                          (t1 + 0.01, "opacity:1"), (t1 + 0.08, "opacity:0.3"),
                          (t1 + 0.15, "opacity:1"), (t1 + 0.22, "opacity:0.4"),
                          (t1 + 0.3, "opacity:1")]
                icons.append(shatter_pieces(css, name, j, x, t0, t1, rng))
        for grey, bumps, back in upgrades:          # grey, waiting; bumped back up
            up = bumps[i]
            # Anything else that moves it meanwhile (a weave's wobble) keeps it grey.
            stops = [(t, p + ";" + GREY.split(";", 1)[1]) if grey < t < up else (t, p) for t, p in stops]
            stops += [(grey, rest), (grey + 0.3, GREY), (up, GREY),
                      (up + 0.1, "transform:rotate(0) scale(0.9);opacity:0.6;filter:grayscale(0.6)"),
                      (up + 0.3, "transform:rotate(0) scale(1.12);opacity:1;filter:grayscale(0)"),
                      (up + 0.45, rest)]
        if stops:
            # Episodes of one icon never overlap, so one rest state works.
            cls = css.episode(rest, merge_stops(stops, rest))
            icons.append(f'<g class="{cls}" style="{BOX}">{use}</g>')
        else:
            icons.append(use)

    # Wall: bricks near an impact fly off; they come back one by one, left to
    # right, once the snake heads back to its meal. The scout nudges some.
    xs = brick_xs()
    flights, order = {}, {}
    for x, t, up, n in bricks:
        for b, bx in enumerate(xs):
            if abs(bx + BRICK / 2 - x) <= 15:
                flights.setdefault(b, []).append((t, up, n))
                order.setdefault(n, []).append(b)
    for b, bx in enumerate(xs):
        rect = (f'<rect x="{bx}" y="{WALL_Y}" width="{BRICK}" height="3" rx="1.5" '
                f'fill="{pal["wall"]}"')
        rest = "transform:translate(0,0) rotate(0);opacity:1"
        stops = [s for cr in crs for b2, t in cr.nudges if b2 == b
                 for s in [(t, rest), (t + 0.1, "transform:translate(0,2px) rotate(0);opacity:1"),
                           (t + 0.25, rest)]]
        away = []                               # while carried off: (from, until)
        for b2, path in (st for cr in crs for st in cr.steals):   # carried into the tile
            if b2 != b:
                continue
            t = path[0][0]
            # Back with the next wall rebuild, or that of the next event whose
            # hole takes this brick (it does not fly then), or at the cycle end.
            later = [events[m]["back"] for m in range(len(events))
                     if events[m]["kind"] == "wall" and events[m]["back"] > t]
            later += [events[n]["back"] + 0.3 * sorted(set(order[n])).index(b)
                      for tf, up, n in flights.get(b, []) if tf > t]
            ret = min(later) if later else T - 1.5
            away.append((t, ret))
            stops += [(t, rest)] + [
                (t1, f"transform:translate({dx:.1f}px,{dy:.1f}px) rotate(90deg);opacity:1")
                for t1, dx, dy in path[1:]]
            t1, dx, dy = path[-1]
            stops += [
                (t1 + 0.01, f"transform:translate({dx:.1f}px,{dy:.1f}px) rotate(90deg);opacity:0"),
                (ret, "transform:translate(0,-14px) rotate(0);opacity:0"),
                (ret + 0.22, "transform:translate(0,1px) rotate(0);opacity:1"),
                (ret + 0.32, rest),
            ]
        for t, up, n in flights.get(b, []):
            if any(a < t < z for a, z in away):
                continue
            dx = rng.uniform(-22, 22)
            dy = rng.uniform(-38, -22) if up else rng.uniform(16, 30)
            rot = rng.uniform(-200, 200)
            back = events[n]["back"] + 0.3 * sorted(set(order[n])).index(b)
            stops += [
                (t, "transform:translate(0,0) rotate(0);opacity:1"),
                (t + 0.25, f"transform:translate({dx * 0.6:.1f}px,{dy:.1f}px) rotate({rot / 2:.0f}deg);opacity:1"),
                (t + 0.8, f"transform:translate({dx:.1f}px,{dy * 0.2 + 30:.1f}px) rotate({rot:.0f}deg);opacity:0"),
                (back, "transform:translate(0,-14px) rotate(0);opacity:0"),
                (back + 0.22, "transform:translate(0,1px) rotate(0);opacity:1"),
                (back + 0.32, "transform:translate(0,0) rotate(0);opacity:1"),
            ]
        if stops:
            cls = css.episode(rest, stops)
            rect += f' class="{cls}" style="{BOX}"'
        parts.append(rect + "/>")

    # Grid: every cell has its empty square; an active cell sits on top and
    # pops away when eaten, then grows back during the backfill.
    empty = pal["cells"][0]
    for (c, r), lvl in sorted(cells.items()):
        x, y = X0 + c * PITCH, Y0 + r * PITCH
        box = f'x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2"'
        parts.append(f'<rect {box} fill="{empty}"/>')
        if lvl:
            stops = []
            for t, what in sorted(grid[c, r]):
                if what == "eat":
                    stops += [(t, "transform:scale(1)"), (t + 0.08, "transform:scale(1.3)"),
                              (t + POP, "transform:scale(0)")]
                else:
                    stops += [(t, "transform:scale(0)"), (t + REFILL, "transform:scale(1)")]
            parts.append(f'<rect {box} fill="{pal["cells"][lvl]}" '
                         f'class="{css.animate(stops)}" style="{BOX}"/>')

    # The bad cell of a HEALTH_WARN: amber blinking until the snake scrubs it.
    for (c, r), alarm, fix in (ev["warn"] for ev in events if "warn" in ev):
        stops, t, on = [(alarm, "opacity:0")], alarm + 0.01, True
        while t < fix:
            stops.append((t, f"opacity:1;fill:{pal['warn'] if on else pal['warn_dim']}"))
            t, on = t + 0.25, not on
        stops += [(fix, f"opacity:1;fill:{pal['warn']}"), (fix + 0.12, "opacity:0")]
        cls = css.episode("opacity:0", merge_stops(stops, f"opacity:0;fill:{pal['warn']}"))
        parts.append(f'<rect x="{X0 + c * PITCH}" y="{Y0 + r * PITCH}" width="{CELL}" '
                     f'height="{CELL}" rx="2" fill="{pal["warn"]}" class="{cls}" opacity="0"/>')

    # Deep scrub: each cell of the row lights up as the snake passes over it.
    for r, passes, _, _ in scrubs:
        for c, t in passes:
            cls = css.episode("opacity:0", [(t - 0.05, "opacity:0"), (t + 0.05, "opacity:0.9"),
                                            (t + 0.6, "opacity:0")])
            parts.append(f'<rect x="{X0 + c * PITCH}" y="{Y0 + r * PITCH}" width="{CELL}" '
                         f'height="{CELL}" rx="2" fill="{pal["ok"]}" class="{cls}" opacity="0"/>')

    # The snake, in a group the tentacles can lift.
    rest = "transform:translate(0,0)"
    lift = css.episode(rest, [s for grab, release in drags for s in [
        (grab, rest), (grab + 0.6, f"transform:translate(0,-{DRAG}px)"),
        (release - 0.1, f"transform:translate(0,-{DRAG}px)"), (release + 0.25, rest)]])
    parts.append(f'<g class="{lift}">{snake_parts(css, tl)}</g>')

    # The scouts: every dot follows its tip's path, each LAG s further behind.
    for (_, dots, tip_r, root_r, home), cr in zip(SCOUTS, crs):
        tip = css.animate([(t, f"transform:translate({num(x)}px,{num(y)}px)")
                           for t, x, y in cr.points + [(T, *home)]])
        for k in reversed(range(dots)):
            parts.append(f'<circle class="{tip}" style="animation-delay:-{k * LAG:.2f}s" '
                         f'r="{tip_r + (root_r - tip_r) * k / (dots - 1):.1f}" fill="{SNAKE}"/>')
        if cr.capes:                            # the vampire cape, on the tip
            worn = css.windows("opacity:1", "opacity:0", cr.capes)
            parts.append(f'<g class="{tip}"><polygon class="{worn}" opacity="0" points="0,-2 -7,8 0,5 7,8" '
                         f'fill="{pal["cape"]}"/></g>')

    parts += icons

    # Tentacles go over the snake so they wrap round it.
    for grab, release, tips, root in tentacles:
        parts.append(draw_tentacles(css, grab, release, tips, root))
        parts.append(draw_ink(css, release, root, pal["ink"], rng))
    for cell, t, root in steals:                # the arm that takes a cell
        parts.append(draw_tentacles(css, t - 0.7, t + 0.1, None, root, [(root + 6, px(cell), -1, 3)]))

    # The scouts' signs.
    box, border, ink = pal["sign"]
    for t, seconds, x, y, text, side in sorted(s for cr in crs for s in cr.signs):
        w, h = 6 * len(text) + 10, 14
        bx = min(WIDTH - w - 4, max(4, x + 8))
        by = y - 22 if side == "up" else y - h / 2
        hidden, shown = "opacity:0;transform:scale(0.6)", "opacity:1;transform:scale(1)"
        cls = css.episode(hidden, [(t, hidden), (t + 0.12, shown), (t + seconds, shown),
                                   (t + seconds + 0.15, hidden)])
        parts.append(f'<g class="{cls}" style="{BOX}" opacity="0">'
                     f'<rect x="{bx}" y="{by}" width="{w}" height="{h}" rx="3" fill="{box}" stroke="{border}"/>'
                     f'<text x="{bx + 5}" y="{by + 10.5}" font-family="ui-monospace,SFMono-Regular,Menlo,'
                     f'Consolas,monospace" font-size="10" fill="{ink}">{escape(text)}</text></g>')

    # Status line: HEALTH_OK with the counts, replaced by each alarm's own
    # text while it lasts.
    font = 'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11"'
    spans = [(a, b) for _, a, b, _ in alarms]
    ok = css.windows("opacity:0", "opacity:1", spans) if spans else None
    parts.append(f'<text x="{X0}" y="{STATUS_Y}" {font} fill="{pal["ok"]}"'
                 + (f' class="{ok}"' if ok else "")
                 + f">HEALTH_OK {OSDS} osds up, {PGS} pgs active+clean</text>")
    for text, a, b, colour in alarms:
        shown = css.windows("opacity:1", "opacity:0", [(a, b)])
        parts.append(f'<text x="{X0}" y="{STATUS_Y}" {font} fill="{colour}" xml:space="preserve" '
                     f'class="{shown}" opacity="0">{escape(text)}</text>')

    # Title, above everything; the animation sits in a group below it.
    sans = ('font-family="-apple-system,BlinkMacSystemFont,&quot;Segoe UI&quot;,'
            '&quot;Noto Sans&quot;,Helvetica,Arial,sans-serif"')
    title = (f'<text x="{WIDTH / 2}" y="30" text-anchor="middle" {sans} font-size="22" '
             f'font-weight="600" fill="{pal["text"]}">{TITLE}</text>'
             f'<text x="{WIDTH / 2}" y="54" text-anchor="middle" {sans} font-size="14" '
             f'fill="{pal["muted"]}">{INTRO}</text>')
    still = "@media (prefers-reduced-motion:reduce){*{animation-play-state:paused!important}}"

    symbols = "".join(tile_symbol(name, theme) for name in ICONS)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT + TOP}" '
           f'viewBox="0 0 {WIDTH} {HEIGHT + TOP}" fill="none">'
           f'<defs>{symbols}{"".join(css.defs)}</defs>'
           f'<style>{"".join(css.rules)}{still}</style>'
           + title + f'<g transform="translate(0,{TOP})">' + "".join(parts) + "</g></svg>\n")
    report = {"cycle": round(T, 3), "loop": LOOP_SECONDS,
              "events": [{"kind": ev["kind"], "start": round(ev["start"], 3),
                          "peak": round(peak(ev), 3), "end": round(ev["end"], 3)}
                         for ev in events],
              "scouts": [{"name": name, "out": round(time_out(cr) / T, 3),
                          "signs": [[round(t, 1), text] for t, _, _, _, text, _ in cr.signs]}
                         for (name, *_), cr in zip(SCOUTS, crs)]}
    return svg, report


def time_out(cr):
    """Seconds the tip spends away from the tile."""
    inside = lambda x, y: tile_x(0) <= x <= tile_x(0) + TILE and ROW_Y <= y <= ROW_Y + TILE
    return sum(t1 - t0 for (t0, x0, y0), (t1, x1, y1) in zip(cr.points, cr.points[1:])
               if not (inside(x0, y0) and inside(x1, y1)))


# --- cli ---------------------------------------------------------------------

def load_calendar(path=None):
    data = (json.loads(Path(path).read_text(encoding="utf-8")) if path
            else fetch_calendar())
    return parse_calendar(data)


def default_seed():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H")


def render(cells, seed, only=None, releases=None):
    """Both themes of one story: ({theme: svg}, report)."""
    svgs, report = {}, {"seed": seed}
    for theme in THEMES:
        # Same seed per theme, so both files tell the same story.
        svg, info = build(cells, theme, seed, only, releases)
        # GitHub serves the file as image/svg+xml: one stray "&" and nothing
        # renders. Browsers forgive it inline in HTML, so check here.
        ET.fromstring(svg)
        assert "events" not in report or report["events"] == info["events"], "themes disagree"
        svgs[theme] = svg
        report[theme] = {"bytes": len(svg)}
        report.update(info)
    return svgs, report


def write_svgs(out, svgs):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for theme, svg in svgs.items():
        (out / f"profile-{theme}.svg").write_text(svg, encoding="utf-8")
    return out


def cmd_build(args):
    cells = load_calendar(args.calendar)
    svgs, report = render(cells, args.seed or default_seed(), args.event, fetch_releases(args.releases))
    write_svgs(args.out, svgs)
    if args.times:
        print(json.dumps(report, indent=1))


PREVIEW_CSS = """
body{margin:0;font:13px ui-monospace,Consolas,monospace;background:#1c2128;color:#c9d1d9}
.row{display:flex}.pane{flex:1;padding:24px;display:flex;justify-content:center}.pane svg{max-width:100%;height:auto}
#dark{background:#0d1117}#light{background:#fff}
.bar{position:sticky;top:0;background:#161b22;border-bottom:1px solid #30363d;padding:8px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
input[type=range]{flex:1;min-width:300px}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;padding:3px 8px;cursor:pointer}button:hover{background:#30363d}
.signs{padding:12px 16px;columns:4;font-size:12px;color:#8b949e}.signs b{color:#c9d1d9}
"""
PREVIEW_JS = """
const anims=document.getAnimations();
const slider=document.getElementById('t'),clock=document.getElementById('clock'),play=document.getElementById('play');
let paused=false;
function now(){return ((anims[0].currentTime||0)/1000)%T;}
function show(t){slider.value=t;clock.textContent=t.toFixed(1)+'s';}
function seek(t){for(const a of anims)a.currentTime=t*1000;show(t);}
function setPaused(p){paused=p;play.textContent=p?'play':'pause';for(const a of anims)p?a.pause():a.play();}
slider.oninput=()=>seek(parseFloat(slider.value));
play.onclick=()=>setPaused(!paused);
for(const b of document.querySelectorAll('button[data-t]'))b.onclick=()=>{seek(parseFloat(b.dataset.t));setPaused(false);};
setInterval(()=>{if(!paused)show(now());},100);
document.addEventListener('keydown',e=>{if(e.key===' '){e.preventDefault();setPaused(!paused);}});
"""


def cmd_preview(args):
    """build, plus preview.html: both themes on GitHub's backgrounds, a time
    scrubber (the Web Animations API seeks every animation exactly), a button
    per event and every sign with its time."""
    cells = load_calendar(args.calendar)
    seed = args.seed or default_seed()
    svgs, report = render(cells, seed, args.event, fetch_releases(args.releases))
    out = write_svgs(args.out, svgs)
    T = report["cycle"]
    buttons = "".join(f'<button data-t="{ev["start"] - 1:.1f}">{ev["kind"]} @{ev["start"]:.0f}s</button>'
                      for ev in report["events"])
    signs = sorted((t, s["name"], text) for s in report["scouts"] for t, text in s["signs"])
    html = (f'<!doctype html><meta charset="utf-8"><title>profile preview {seed}</title>'
            f"<style>{PREVIEW_CSS}</style>"
            f'<div class="bar"><b>seed {seed}</b> cycle {T:.1f}s · {report["dark"]["bytes"]} B '
            f'<button id="play">pause</button><input type="range" id="t" min="0" max="{T:.2f}" step="0.1" value="0">'
            f'<span id="clock">0.0s</span>{buttons}</div>'
            f'<div class="row"><div class="pane" id="dark">{svgs["dark"]}</div>'
            f'<div class="pane" id="light">{svgs["light"]}</div></div>'
            f'<div class="signs">{"".join(f"<div><b>{t:6.1f}</b> {who}: {escape(text)}</div>" for t, who, text in signs)}</div>'
            f"<script>const T={T};{PREVIEW_JS}</script>\n")
    (out / "preview.html").write_text(html, encoding="utf-8")
    print(out / "preview.html")


def variants(cells):
    """Calendars of the same shape to check against: as it is, empty, full,
    a few scattered cells, and Mondays only."""
    return {
        "real": cells,
        "empty": {c: 0 for c in cells},
        "full": {c: 4 for c in cells},
        "sparse": {c: 1 if (c[0] * ROWS + c[1]) % 50 == 0 else 0 for c in cells},
        "mondays": {c: 2 if c[1] == 1 else 0 for c in cells},
    }


def cmd_check(args):
    """Every variant of the calendar, then every event kind alone, with
    several seeds spread over the year; stops at the first failure."""
    cells = load_calendar(args.calendar)
    releases = fetch_releases(args.releases)
    day0 = datetime.date(2026, 1, 1)
    seeds = [f"{day0 + datetime.timedelta(days=37 * i)}T{i % 24:02d}" for i in range(args.seeds)]
    runs = ([(name, cs, None) for name, cs in variants(cells).items()]
            + [("real", cells, kind) for kind in EVENTS])
    for seed in seeds:
        for name, cs, kind in runs:
            label = f"{seed} {name}" + (f" --event {kind}" if kind else "")
            try:
                svgs, report = render(cs, seed, kind, releases)
                kinds = {ev["kind"] for ev in report["events"]}
                size, cycle = max(map(len, svgs.values())), report["cycle"]
                assert 150 < cycle < 450, f"cycle {cycle:.0f} s"
                assert size < 400_000, f"{size} bytes"
                if not any(cs.values()):
                    assert not kinds, f"events on an empty grid: {kinds}"
                elif kind:
                    assert kinds == {kind}, f"kinds {kinds}"
                else:
                    assert kinds == set(EVENTS), f"missing {set(EVENTS) - kinds}"
                for s in report["scouts"]:
                    assert s["out"] <= 0.8, f"{s['name']} out {s['out']:.0%} of the time"
            except Exception as e:
                sys.exit(f"check failed: {label}: {type(e).__name__}: {e}")
            print(f"{label}: {report['cycle']:.0f} s, {report['dark']['bytes']} B, {len(report['events'])} events")
    print(f"ok: {len(seeds) * len(runs)} builds")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tiles", help="refresh assets/tiles/")
    cmds = {"tiles": cmd_tiles, "build": cmd_build, "preview": cmd_preview, "check": cmd_check}
    for name, doc in (("build", "write profile-{dark,light}.svg"),
                      ("preview", "build, plus preview.html with a time scrubber"),
                      ("check", "build many variants and seeds, fail on the first bad one")):
        p = sub.add_parser(name, help=doc)
        p.add_argument("--calendar", help="saved GraphQL response instead of the API")
        p.add_argument("--releases", help="saved releases.yml instead of fetching it")
        if name == "check":
            p.add_argument("--seeds", type=int, default=3, help="seeds per variant (default 3)")
            continue
        p.add_argument("--out", default="dist")
        p.add_argument("--event", choices=EVENTS, help="use only this event")
        p.add_argument("--seed", help="default: the current UTC hour")
        p.add_argument("--times", action="store_true", help="print the schedule as JSON")
    args = parser.parse_args()
    cmds[args.cmd](args)


if __name__ == "__main__":
    main()
