"""Draw the LLMDyno pixel-art mascot: a dinosaur with a rocket strapped to its back, on a treadmill (a dyno).

Everything is drawn on a 48x48 grid as named layers, so the web UI can animate it by switching layers:
running legs A/B, belt frames, booster flames, blinking eye, a podium pose for judging, and so on.

    python scripts/make_logo.py

Writes frontend/src/dyno-sprite.ts (layers for the animated component), frontend/public/favicon.svg,
docs/images/logo.svg, docs/images/banner.svg and animated docs/images/dyno-running.svg / dyno-judging.svg.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZE = 48

PALETTE = {
    "bg": "#262552",     # tile
    "star": "#8b8bf0",
    "star2": "#5b5bd6",
    "W": "#f1f0fa",      # dino
    "S": "#bdbcd6",      # dino shade: far leg, belly
    "E": "#1b1a38",      # eye, straps, outlines
    "R": "#ef4444",      # rocket
    "r": "#b42323",      # rocket shade
    "w": "#9fd0ff",      # rocket window
    "G": "#9ca3af",      # nozzle
    "F": "#fb923c",      # flame
    "Y": "#fde047",      # hot flame
    "B": "#3d3c6b",      # belt
    "b": "#7a79b8",      # belt marks
    "D": "#17163a",      # deck
    "P": "#b8b8cc",      # treadmill frame
    "L": "#4ade80",      # console display
    "l": "#14532d",      # display, dark segments
    "K": "#4b4a8a",      # podium face
    "k": "#8b8bf0",      # podium top edge
    "1": "#fde047",      # gold
    "2": "#e2e8f0",      # silver
    "3": "#fb923c",      # bronze
    "C1": "#f472b6",     # confetti
    "C2": "#4ade80",
    "C3": "#60a5fa",
}


class Layer:
    def __init__(self):
        self.px = {}

    def h(self, y, x1, x2, c):
        for x in range(x1, x2 + 1):
            self.px[(x, y)] = c
        return self

    def dot(self, x, y, c):
        self.px[(x, y)] = c
        return self

    def rows(self, spec, c):
        """spec: {y: (x1, x2) or [(x1, x2), ...]}"""
        for y, rng in spec.items():
            for x1, x2 in (rng if isinstance(rng, list) else [rng]):
                self.h(y, x1, x2, c)
        return self

    def runs(self):
        out = []
        for y in range(SIZE):
            x = 0
            while x < SIZE:
                c = self.px.get((x, y))
                if c is None:
                    x += 1
                    continue
                x2 = x
                while x2 < SIZE and self.px.get((x2, y)) == c:
                    x2 += 1
                out.append((x, y, x2 - x, c))
                x = x2
        return out


L = {}

# ---------------------------------------------------------------- background
L["stars"] = Layer().dot(7, 3, "star").dot(42, 4, "star").dot(3, 7, "star2").dot(23, 5, "star2").dot(16, 2, "star2")

# ---------------------------------------------------------------- treadmill
mill = Layer()
mill.h(40, 4, 41, "B").h(41, 3, 42, "B").h(42, 3, 42, "D").h(43, 5, 6, "D").h(43, 39, 40, "D")
for y in range(22, 40):
    mill.h(y, 41, 42, "P")
mill.h(18, 37, 46, "P").h(21, 37, 46, "P").dot(37, 19, "P").dot(37, 20, "P").dot(46, 19, "P").dot(46, 20, "P")
mill.h(24, 34, 40, "P")                                   # handlebar
L["mill"] = mill
L["screen_off"] = Layer().h(19, 38, 45, "l").h(20, 38, 45, "l")
# a little speed readout: two blocky digits
L["screen_on"] = Layer().h(19, 38, 45, "l").h(20, 38, 45, "l").h(19, 39, 40, "L").dot(39, 20, "L").h(19, 42, 44, "L").dot(44, 20, "L").dot(42, 20, "L")
for k in range(3):                                         # belt marks; the belt runs backwards under the dino
    lay = Layer()
    for x in range(4 + 2 * k, 41, 6):
        lay.h(41, x, min(x + 1, 41), "b")
    L[f"belt{k}"] = lay

# ---------------------------------------------------------------- dino body (head, neck, torso, tail)
body = Layer().rows({
    9: (27, 33), 10: (26, 34), 11: (26, 34), 12: (26, 34), 13: (26, 34),
    14: (26, 31), 15: (26, 33), 16: (22, 30),               # open mouth notch at row 14
    17: (21, 29), 18: (20, 29), 19: [(3, 4), (18, 29)], 20: [(3, 6), (16, 29)],
    21: (5, 29), 22: (8, 28), 23: (10, 28), 24: (11, 27), 25: (12, 27), 26: (13, 26),
    27: (14, 25), 28: (15, 24), 29: (16, 23),
}, "W")
body.rows({27: (14, 15), 28: (15, 16), 29: (16, 17)}, "S")   # belly shading
L["body"] = body
L["eye"] = Layer().dot(30, 11, "E")
L["arm_grip"] = Layer().rows({20: (30, 31), 21: (31, 32), 22: (32, 33), 23: (33, 34)}, "W")
L["arm_rest"] = Layer().rows({20: (30, 31), 21: (31, 32), 22: (32, 32)}, "W")

# ---------------------------------------------------------------- legs
L["legs_stand"] = Layer().rows({
    **{y: (16, 18) for y in range(30, 38)}, 38: (16, 19), 39: (15, 20)}, "S").rows({
    **{y: (20, 22) for y in range(30, 38)}, 38: (20, 23), 39: (20, 25)}, "W")
L["legs_a"] = Layer().rows({
    30: (15, 18), 31: (14, 17), 32: (13, 16), 33: (12, 15), 34: (11, 14), 35: (10, 13), 36: (9, 12),
    37: (9, 11), 38: (8, 10), 39: (6, 10)}, "S").rows({
    30: (19, 22), 31: (20, 23), 32: (21, 24), 33: (22, 25), 34: (23, 25), 35: (23, 25), 36: (23, 25),
    37: (23, 27)}, "W")
L["legs_b"] = Layer().rows({
    30: (19, 21), 31: (20, 22), 32: (21, 23), 33: (22, 24), 34: (22, 24), 35: (22, 24), 36: (22, 26)}, "S").rows({
    30: (17, 20), 31: (16, 19), 32: (15, 18), 33: (14, 17), 34: (13, 16), 35: (12, 15), 36: (11, 14),
    37: (10, 13), 38: (9, 12), 39: (7, 12)}, "W")
# sitting on the edge of the podium, legs dangling over its front
# passing frames between the strides: one leg planted straight under the hip while the other swings through,
# so a run cycle reads  /  |  \  |  instead of flipping straight between the two strides
L["legs_p1"] = Layer().rows({                               # near leg planted, far leg swinging forward
    30: (16, 18), 31: (16, 18), 32: (16, 18), 33: (15, 18), 34: (13, 17), 35: (12, 14)}, "S").rows({
    **{y: (20, 22) for y in range(30, 39)}, 39: (20, 25)}, "W")
L["legs_p2"] = Layer().rows({                               # far leg planted, near leg swinging forward
    **{y: (17, 19) for y in range(30, 39)}, 39: (16, 21)}, "S").rows({
    30: (19, 22), 31: (19, 22), 32: (19, 22), 33: (18, 22), 34: (17, 21), 35: (16, 18)}, "W")
L["legs_sit"] = Layer().rows({28: (16, 24), 29: (17, 25), 30: (23, 25), 31: (23, 25), 32: (23, 25), 33: (23, 25),
                              34: (23, 27)}, "S").rows({
    26: (20, 27), 27: (20, 28), 28: (22, 29), 29: (26, 29), 30: (27, 29), 31: (27, 29), 32: (27, 29), 33: (27, 29),
    34: (27, 29), 35: (27, 31)}, "W")

# ---------------------------------------------------------------- rocket, straps, flames
rocket = Layer().rows({12: (11, 19), 13: (9, 21), 14: (9, 22), 15: (9, 22), 16: (9, 21), 17: (11, 19)}, "R")
rocket.rows({15: (9, 22), 16: (9, 21), 17: (11, 19)}, "r")
rocket.rows({10: (8, 9), 11: (8, 10)}, "R").rows({18: (8, 10), 19: (8, 9)}, "r")
rocket.rows({13: (7, 8), 14: (7, 8), 15: (7, 8), 16: (7, 8)}, "G")
rocket.dot(18, 13, "w").dot(19, 13, "w").dot(18, 14, "w")
for x in (13, 17):                                          # straps around rocket and torso
    for y in range(12, 22 if x == 17 else 23):
        rocket.dot(x, y, "E")
L["rocket"] = rocket
L["flame_a"] = Layer().rows({13: (4, 6), 14: [(1, 3), (4, 6)], 15: [(0, 2), (3, 6)], 16: (3, 6)}, "F").rows(
    {14: (4, 6), 15: (3, 6)}, "Y")
L["flame_b"] = Layer().rows({12: (5, 5), 13: (3, 6), 14: (2, 6), 15: (1, 6), 16: (4, 6), 17: (2, 2)}, "F").rows(
    {14: (4, 6), 15: (4, 6)}, "Y")
L["puff"] = Layer().rows({13: (4, 5), 14: (2, 6), 15: (3, 6), 16: (5, 6)}, "G")      # cold booster: a wisp of smoke

# ---------------------------------------------------------------- judging: podium and thought bubble
pod = Layer()
pod.rows({y: (16, 31) for y in range(31, 44)}, "K").h(30, 16, 31, "k")
pod.rows({y: (4, 15) for y in range(36, 44)}, "K").h(35, 4, 15, "k")
pod.rows({y: (32, 43) for y in range(39, 44)}, "K").h(38, 32, 43, "k")
pod.rows({35: (18, 19), 36: (17, 19), 37: (18, 19), 38: (18, 19), 39: (18, 19), 40: (17, 20)}, "1")  # "1"
pod.rows({38: (8, 11), 39: (11, 11), 40: (8, 11), 41: (8, 8), 42: (8, 11)}, "2")                    # "2"
pod.rows({39: (36, 39), 40: (39, 39), 41: (37, 39), 42: (39, 39), 43: (36, 39)}, "3")                # "3"
L["podium"] = pod
bubble = Layer().h(1, 35, 43, "W").rows({y: (34, 44) for y in range(2, 6)}, "W").h(6, 35, 43, "W")
bubble.dot(33, 7, "W").dot(32, 8, "W")
L["bubble"] = bubble
for i, x in enumerate((36, 39, 42)):
    L[f"dot{i}"] = Layer().rows({3: (x, x + 1), 4: (x, x + 1)}, "E")

# ---------------------------------------------------------------- celebration confetti (two frames)
L["confetti_a"] = Layer().dot(8, 6, "C1").dot(14, 3, "C2").dot(38, 9, "C3").dot(44, 14, "C1").dot(20, 1, "Y").dot(4, 12, "C3")
L["confetti_b"] = Layer().dot(9, 8, "C2").dot(13, 5, "C3").dot(39, 11, "C1").dot(43, 16, "Y").dot(21, 3, "C1").dot(5, 14, "C2")


def tile_path(s=SIZE, k=2):
    """Rounded square with stair-stepped (pixel) corners."""
    pts = [(2 * k, 0), (s - 2 * k, 0), (s - 2 * k, k), (s - k, k), (s - k, 2 * k), (s, 2 * k), (s, s - 2 * k),
           (s - k, s - 2 * k), (s - k, s - k), (s - 2 * k, s - k), (s - 2 * k, s), (2 * k, s), (2 * k, s - k),
           (k, s - k), (k, s - 2 * k), (0, s - 2 * k), (0, 2 * k), (k, 2 * k), (k, k), (2 * k, k)]
    return "M" + " L".join(f"{x} {y}" for x, y in pts) + " Z"


POSES = {
    # static pictures used for the favicon, README logo and banner
    "logo": ["stars", "mill", "screen_on", "belt0", "body", "eye", "arm_grip", "legs_a", "rocket", "flame_a"],
}


def svg_rects(names, indent="  "):
    out = []
    for n in names:
        for x, y, w, c in L[n].runs():
            out.append(f'{indent}<rect x="{x}" y="{y}" width="{w}" height="1" fill="{PALETTE[c]}"/>')
    return "\n".join(out)


def icon_svg(names):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" shape-rendering="crispEdges" role="img" '
            f'aria-label="LLMDyno logo">\n  <title>LLMDyno</title>\n  <path d="{tile_path()}" fill="{PALETTE["bg"]}"/>\n'
            f'{svg_rects(names)}\n</svg>\n')


def banner_svg(names):
    """1280x640 social preview / README banner: the mascot at 10x, the wordmark and a tagline."""
    pix = "'Press Start 2P', 'Courier New', ui-monospace, monospace"
    sans = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" width="1280" height="640" role="img" aria-label="LLMDyno: benchmark local and cloud LLMs as coding agents">
  <title>LLMDyno: put your LLM on the dyno</title>
  <rect width="1280" height="640" fill="#14132e"/>
  <g fill="#23224a" shape-rendering="crispEdges"><rect y="584" width="1280" height="8"/><rect y="608" width="1280" height="8"/><rect y="632" width="1280" height="8"/></g>
  <g transform="translate(80 80) scale(10)" shape-rendering="crispEdges">
    <path d="{tile_path()}" fill="{PALETTE["bg"]}"/>
{svg_rects(names, "    ")}
  </g>
  <text x="640" y="262" font-family="{pix}" font-size="64" fill="#f1f0fa">LLM<tspan fill="#fb923c">Dyno</tspan></text>
  <text x="642" y="336" font-family="{sans}" font-size="32" font-weight="600" fill="#f1f0fa">Put your LLM on the dyno.</text>
  <text x="642" y="388" font-family="{sans}" font-size="24" fill="#bdbcd6">Benchmark local and cloud models as coding agents:</text>
  <text x="642" y="422" font-family="{sans}" font-size="24" fill="#bdbcd6">VRAM fit, speed, cost, correctness and code quality.</text>
  <text x="642" y="488" font-family="{sans}" font-size="20" fill="#8b8bf0">llama.cpp · OpenAI · Anthropic · Gemini · DeepSeek · Kimi · Qwen · and more</text>
</svg>
'''


ANIM_CSS = """
@keyframes f2 { 0%, 49.99% { visibility: visible } 50%, 100% { visibility: hidden } }
@keyframes f3 { 0%, 33.32% { visibility: visible } 33.33%, 100% { visibility: hidden } }
@keyframes f4 { 0%, 24.99% { visibility: visible } 25%, 100% { visibility: hidden } }
@keyframes eye { 0%, 93.99% { visibility: visible } 94%, 97.99% { visibility: hidden } 98%, 100% { visibility: visible } }
@keyframes d0 { 0%, 24.99% { visibility: hidden } 25%, 100% { visibility: visible } }
@keyframes d1 { 0%, 49.99% { visibility: hidden } 50%, 100% { visibility: visible } }
@keyframes d2 { 0%, 74.99% { visibility: hidden } 75%, 100% { visibility: visible } }
.l4a { animation: f4 .48s infinite } .l4b { animation: f4 .48s -.36s infinite } .l4c { animation: f4 .48s -.24s infinite } .l4d { animation: f4 .48s -.12s infinite }
.b3a { animation: f3 .3s infinite } .b3b { animation: f3 .3s -.2s infinite } .b3c { animation: f3 .3s -.1s infinite }
.fla { animation: f2 .14s infinite } .flb { animation: f2 .14s -.07s infinite }
.eye { animation: eye 3.8s infinite } .d0 { animation: d0 1.8s infinite } .d1 { animation: d1 1.8s infinite } .d2 { animation: d2 1.8s infinite }
@media (prefers-reduced-motion: reduce) { * { animation: none !important } .l4b, .l4c, .l4d, .b3b, .b3c, .flb { visibility: hidden } }
"""
ANIMATED = {
    "running": [("stars", ""), ("mill", ""), ("screen_on", ""), ("belt2", "b3a"), ("belt1", "b3b"), ("belt0", "b3c"),
                ("body", ""), ("eye", "eye"), ("arm_grip", ""), ("legs_a", "l4a"), ("legs_p1", "l4b"), ("legs_b", "l4c"),
                ("legs_p2", "l4d"), ("rocket", ""), ("flame_a", "fla"), ("flame_b", "flb")],
    "judging": [("stars", ""), ("podium", ""), ("body", ""), ("eye", "eye"), ("arm_rest", ""), ("legs_sit", ""),
                ("rocket", ""), ("bubble", ""), ("dot0", "d0"), ("dot1", "d1"), ("dot2", "d2")],
}


def animated_svg(pose, px=192):
    """Self-contained animated SVG (CSS frame animation), for the README and docs."""
    nl = "\n"
    groups = []
    for name, cls in ANIMATED[pose]:
        attr = f' class="{cls}"' if cls else ""
        groups.append(f"  <g{attr}>{nl}{svg_rects([name], '    ')}{nl}  </g>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="{px}" height="{px}" shape-rendering="crispEdges" '
            f'role="img" aria-label="LLMDyno mascot: {pose}">{nl}  <title>LLMDyno mascot ({pose})</title>{nl}'
            f'  <style>{ANIM_CSS}</style>{nl}  <path d="{tile_path()}" fill="{PALETTE["bg"]}"/>{nl}'
            + nl.join(groups) + f"{nl}</svg>{nl}")


def sprite_ts():
    lines = ["// Generated by scripts/make_logo.py; edit the drawing there, not here.",
             f"export const DYNO_TILE = {tile_path()!r};",
             f"export const DYNO_PALETTE: Record<string, string> = {{{', '.join(f'{k!r}: {v!r}' for k, v in PALETTE.items())}}};",
             "/** layer name -> runs of [x, y, width, palette key] */",
             "export const DYNO_LAYERS: Record<string, [number, number, number, string][]> = {"]
    for name, lay in L.items():
        lines.append(f"  {name}: [{', '.join(f'[{x},{y},{w},{c!r}]' for x, y, w, c in lay.runs())}],")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main():
    icon = icon_svg(POSES["logo"])
    for p in (ROOT / "frontend/public/favicon.svg", ROOT / "docs/images/logo.svg"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(icon, encoding="utf-8")
    (ROOT / "docs/images/banner.svg").write_text(banner_svg(POSES["logo"]), encoding="utf-8")
    (ROOT / "frontend/src/dyno-sprite.ts").write_text(sprite_ts(), encoding="utf-8")
    for pose in ANIMATED:
        (ROOT / f"docs/images/dyno-{pose}.svg").write_text(animated_svg(pose), encoding="utf-8")
    print(f"{len(L)} layers; wrote favicon.svg, logo.svg, banner.svg, dyno-sprite.ts")


if __name__ == "__main__":
    main()
