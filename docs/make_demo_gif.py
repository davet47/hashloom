"""Generate docs/demo.gif — the README demo, per the storyboard in demo.md.

Renders the whole gif with Pillow (no screen recording): title card, the
benchmark number, then the Claude Code -> hashloom regeneration loop on
examples/sales (get_contract packet, the edit, verify miss/hit, status).
The scene text mirrors the real project: refresh the numbers from
`uv run python bench/benchmark.py` and a real `get_contract` packet when
they drift.

Run:  uv run --with pillow python docs/make_demo_gif.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1149, 916
TITLEBAR_H = 38
CAPTION_Y = 850

# palette sampled from the original recording
BG_CARD = (18, 18, 26)
BG_TERM = (24, 24, 32)
BG_BAR = (48, 48, 62)
BG_CAPTION = (16, 16, 22)
FG = (203, 203, 209)
GRAY = (132, 131, 141)
SUBTLE = (140, 140, 155)
THREAD = (70, 70, 95)
CYAN = (110, 200, 230)
TITLE_CYAN = (120, 210, 240)
GREEN = (110, 220, 140)
YELLOW = (240, 210, 110)
MAGENTA = (207, 151, 215)
RED = (235, 120, 120)
LIGHTS = [(235, 110, 105), (245, 191, 79), (95, 185, 119)]

FONT = "/System/Library/Fonts/Menlo.ttc" if sys.platform == "darwin" else (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
)
BOLD_INDEX = 1 if sys.platform == "darwin" else 0


def font(size: int, bold: bool = False):
    if sys.platform == "darwin":
        return ImageFont.truetype(FONT, size, index=1 if bold else 0)
    path = FONT.replace(".ttf", "-Bold.ttf") if bold else FONT
    return ImageFont.truetype(path, size)


MONO = font(24)
MONO_BOLD = font(24, bold=True)
CHAR_W = MONO.getlength("m")
LINE_H = 30
TEXT_X = 18
FIRST_ROW_Y = 55  # top of row 0; original rows center on y=67, 97, ...

frames: list[Image.Image] = []
durations: list[int] = []


def emit(img: Image.Image, ms: int) -> None:
    frames.append(img)
    durations.append(ms)


def title_card() -> Image.Image:
    img = Image.new("RGB", (W, H), BG_CARD)
    d = ImageDraw.Draw(img)
    big = font(64, bold=True)
    small = font(28)
    d.text((W / 2, 404), "hashloom", font=big, fill=TITLE_CYAN, anchor="mm")
    d.text((W / 2, 484), "contracts are warp, code is weft", font=small, fill=SUBTLE, anchor="mm")
    for i in range(8):
        x = W // 2 - 140 + i * 40
        d.rectangle([x - 1, 528, x + 1, 608], fill=THREAD)
    return img


def terminal(caption: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG_TERM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, TITLEBAR_H], fill=BG_BAR)
    for i, color in enumerate(LIGHTS):
        d.ellipse([15 + i * 22, 11, 29 + i * 22, 25], fill=color)
    d.text((W / 2, TITLEBAR_H / 2), "claude code — examples/sales", font=font(20), fill=SUBTLE, anchor="mm")
    d.rectangle([0, CAPTION_Y, W, H], fill=BG_CAPTION)
    d.text((TEXT_X, 884), caption, font=font(26), fill=FG, anchor="lm")
    return img, d


# a scene line is (row, segments); a segment is (text, color) or (text, color, bold)
def draw_lines(d: ImageDraw.ImageDraw, lines, cursor: tuple[int, int] | None = None) -> None:
    for row, segments in lines:
        x = TEXT_X
        for seg in segments:
            text, color, bold = (*seg, False) if len(seg) == 2 else seg
            f = MONO_BOLD if bold else MONO
            d.text((x, FIRST_ROW_Y + row * LINE_H + LINE_H / 2), text, font=f, fill=color, anchor="lm")
            x += CHAR_W * len(text)
    if cursor is not None:
        row, col = cursor
        cx = TEXT_X + CHAR_W * col
        cy = FIRST_ROW_Y + row * LINE_H
        d.rectangle([cx, cy + 4, cx + CHAR_W - 2, cy + LINE_H - 4], fill=FG)


def render(caption: str, lines, cursor=None) -> Image.Image:
    img, d = terminal(caption)
    draw_lines(d, lines, cursor)
    return img


def type_line(caption: str, done_lines, row: int, segments, chars_per_frame: int = 2, ms: int = 70) -> None:
    """Emit typing frames for one line; done_lines are already-complete lines."""
    flat = [(t, c, s[2] if len(s) > 2 else False) for s in segments for t, c in [(s[0], s[1])]]
    total = sum(len(t) for t, _, _ in flat)
    for n in range(chars_per_frame, total + 1, chars_per_frame):
        partial, remaining = [], n
        for t, c, b in flat:
            take = min(len(t), remaining)
            partial.append((t[:take], c, b))
            remaining -= take
            if remaining == 0:
                break
        emit(render(caption, [*done_lines, (row, partial)], cursor=(row, n)), ms)
    emit(render(caption, [*done_lines, (row, flat)], cursor=(row, total)), 140)


ARROW = [("→ ", MAGENTA), ("MCP ", CYAN, True)]

# -- scene 0: title card ------------------------------------------------------
emit(title_card(), 2340)

# -- scene 1: the benchmark number (numbers from bench/benchmark.py) ----------
CAP1 = "5.2× fewer tokens per regeneration."
line0 = [("# the number, from the repo root", GRAY)]
line1 = [("$ ", GRAY), ("uv run python bench/benchmark.py", FG)]
type_line(CAP1, [], 0, line0)
type_line(CAP1, [(0, line0)], 1, line1)
rule = "─" * 42
table = [
    (0, line0),
    (1, line1),
    (3, [("  regeneration token cost  (lower is better)", GRAY)]),
    (4, [("  " + rule, GRAY)]),
    (5, [("  baseline   (raw files)     1,932 tok", FG)]),
    (6, [("  hashloom   (spec packet)     ", FG), ("374 tok", GREEN, True)]),
    (7, [("  " + rule, GRAY)]),
    (8, [("  speedup                ", FG), ("5.2× fewer tokens", YELLOW, True)]),
]
emit(render(CAP1, table), 2600)

# -- scene 2: get_contract — one small packet (real packet, 305 tokens) -------
CAP2 = "One ~300-token packet: spec + dep signatures + callers."
call2 = [*ARROW, ('get_contract("revenue_by_region")', FG)]
type_line(CAP2, [], 0, call2)
packet = [
    (0, call2),
    (2, [("  spec:      ", GRAY), ("sum of completed-sale amounts per region", FG)]),
    (3, [("  signature: ", GRAY), ("(sales: list[Sale]) -> dict[Region, float]", CYAN)]),
    (4, [("  deps:      ", GRAY), ("Sale  Region  included_sales()", CYAN)]),
    (5, [("  callers:   ", GRAY), ("revenue_share_by_region()", CYAN)]),
    (6, [("  ── packet: ", GRAY), ("305 tokens", GREEN, True)]),
]
emit(render(CAP2, packet), 3120)

# -- scene 3: the edit (the real impl in examples/sales) ----------------------
CAP3 = "It weaves the weft."
header = [("✎ ", YELLOW), ("editing ", YELLOW, True), ("src/metrics.py::revenue_by_region", CYAN)]
code = [
    (2, [("  ", FG), ("def", MAGENTA), (" revenue_by_region(sales):", FG)]),
    (3, [("      revenue = {}", FG)]),
    (4, [("      ", FG), ("for", MAGENTA), (" sale ", FG), ("in", MAGENTA), (" included_sales(sales):", FG)]),
    (5, [("          revenue[sale.region] = (", FG)]),
    (6, [("              revenue.get(sale.region, 0.0) + sale.amount)", FG)]),
    (7, [("      ", FG), ("return", MAGENTA), (" revenue", FG)]),
]
emit(render(CAP3, [(0, header)]), 490)
for i in range(1, len(code) + 1):
    emit(render(CAP3, [(0, header), *code[:i]]), 350)
emit(render(CAP3, [(0, header), *code]), 1340)

# -- scene 4: verify — pytest on a miss, cached-pass on a hit -----------------
CAP4 = "Second run: cached-pass, no pytest."
call4 = [*ARROW, ('verify(["revenue_by_region"])', FG)]
type_line(CAP4, [], 0, call4)
miss = [
    (0, call4),
    (2, [("  impl hash changed → running pytest …", GRAY)]),
    (3, [("  revenue_by_region   ", FG), ("pass", GREEN, True), ("   (pytest, 1 test)", GRAY)]),
]
emit(render(CAP4, miss), 2130)
type_line(CAP4, miss, 4, call4)
hit = [
    *miss,
    (4, call4),
    (5, [("  revenue_by_region   ", FG), ("cached-pass", CYAN, True), ("   (no pytest)", GRAY)]),
]
emit(render(CAP4, hit), 2480)

# -- scene 5: status — the loop, in a few hundred tokens ----------------------
CAP5 = "5.2× fewer tokens, verified."
call5 = [*ARROW, ("status()", FG)]
type_line(CAP5, [], 0, call5)
status = [
    (0, call5),
    (2, [("  tokens served       ", GRAY), ("305", GREEN, True)]),
    (3, [("  tokens (raw files)  ", GRAY), ("1,932", RED, True)]),
    (4, [("  cache hit-rate      ", GRAY), ("50%  ", FG), ("(1 miss, 1 hit)", GRAY)]),
    (5, [("  dirty units         ", GRAY), ("0", GREEN, True)]),
    (6, [("  interpreter         ", GRAY), (".venv/bin/python  ", FG), ("(uv)", GRAY)]),
]
emit(render(CAP5, status), 3120)

# -- scene 6: closing title card ----------------------------------------------
emit(title_card(), 1980)

out = Path(__file__).parent / "demo.gif"
frames[0].save(
    out,
    save_all=True,
    append_images=frames[1:],
    duration=durations,
    loop=0,
    optimize=True,
)
total_s = sum(durations) / 1000
print(f"wrote {out} — {len(frames)} frames, {total_s:.1f}s, {out.stat().st_size // 1024} KB")
