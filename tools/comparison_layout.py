#!/usr/bin/env python3
"""Layout owner for the comparison frame, driven by a profile's [comparison].

The comparison video shows one encode beside its source master and reference
recordings. This module owns the frame: the canvas, the slot geometry, the
drawing, the overlay PNG the videos are composited under, and the panel
rectangles the muxing stage places video into, so the drawn frame and the video
placement come from one definition.

What is per-source lives in the profile TOML - which footage fills each panel,
how the panels are synchronised, and every piece of text on the frame.
What is a layout rule lives here: the canvas size, the slots, the gaps, the
type sizes, and the colours.

Panels are sized from a displayed aspect, never from a nominal 4:3. An H40
screen is a 320x224 aperture with pixel aspect 32:35, displayed as 292.57x224
(1.3061), so a 4:3 panel would stretch it horizontally by 2.1%.

Sizes and positions are derived, not typed twice. The frame is one headline
plus four panels, and the left column takes all the height between them: its
top follows the headline, its bottom is fixed by the audio note that has to
clear the bottom margin, and its width follows from its aspect. Everything else
follows from that. The right column starts a gap past the left column, so
growing the playback panel narrows the right column rather than overlapping it.
The upper right row's height is whatever makes both its panels, plus one inner
gap, span that column exactly, which keeps their outer edges flush even when
their widths differ. The lower panel's bottom edge is flush with the left
column's, so both spec lines share one baseline; its height is the smaller of
what the row above leaves it and what the column's width allows.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from encode_config import load_profile
# The same set of scaling filters the encoder's own geometry offers, so a
# panel cannot be given a filter the rest of the project does not know.
from video_geometry import RESIZE_FILTERS

ROOT = Path(__file__).resolve().parents[1]

CANVAS = (1920, 1080)

# Noto Sans CJK carries both weights and Japanese glyphs, so a label may be
# written in either language without switching families.
FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

BG = (14, 16, 20, 255)
TITLE_FILL = (248, 249, 252, 255)
# The codec's short name leads the headline in an accent colour, so the frame
# names the codec at a glance without a second line spelling it out.
BADGE_FILL = (77, 182, 255, 255)
LABEL_FILL = (240, 242, 246, 255)
SPEC_FILL = (205, 210, 220, 255)
NOTE_FILL = (205, 210, 220, 255)
STROKE = (235, 238, 243, 255)
PLACEHOLDER = (72, 80, 94, 255)
PLACEHOLDER_TEXT = (205, 210, 220, 255)

TITLE_SIZE = 42
LABEL_SIZE = 24
SPEC_SIZE = 20
NOTE_SIZE = 22
# Line advance when a spec runs to more than one line.
SPEC_LINE_HEIGHT = 26
# Clearance a baseline needs so its descenders stay off the bottom margin.
DESCENDER = 6

MARGIN = 48
STROKE_WIDTH = 4
# Single headline, on the same left edge as everything else.
HEADLINE_BASELINE = 62
# Gap from the headline's baseline to the first panel label's baseline. The
# headline needs more air under it than a label does above its own frame, or it
# reads as part of the first panel rather than as the frame's title.
HEADLINE_TO_LABEL = 64
# Gap between the badge and the headline that follows it.
BADGE_GAP = 20
# Gap from a panel's frame to the label above it and the spec line below it.
LABEL_GAP = 27
SPEC_GAP = 31
# Gap from the left column's spec line to the audio note under it.
NOTE_GAP = 34
# Gap between the two columns. The gap between the upper row's two panels is
# derived, not set: they are justified to the column's edges, so INNER_GAP is
# only the floor that derivation is allowed to reach - enough that two frames
# read as two panels rather than one split box.
COLUMN_GAP = 36
INNER_GAP = 24
# Clear space between the upper row's last spec line and the lower row's label.
# This one is deliberately not tightened: a two-line spec above already pushes
# the lower panel down, so shrinking it too would crowd that panel.
ROW_GAP = 60

# Panel top edge, shared by the left column and the right column's upper row.
PANEL_TOP = HEADLINE_BASELINE + HEADLINE_TO_LABEL + LABEL_GAP

RIGHT_RIGHT = CANVAS[0] - MARGIN

# A profile picks its arrangement by which slots its panels use. Four panels
# put two side by side in the right column's upper row with a wide one beneath;
# three stack the right column instead. A source whose 1993 release is neither
# the same music nor full motion video has nothing to put in a fourth panel.
LAYOUTS = {
    "four": ("main", "top_left", "top_right", "lower"),
    "three": ("main", "right_top", "right_bottom"),
}
SLOTS = tuple(sorted({slot for slots in LAYOUTS.values() for slot in slots}))


@dataclass(frozen=True)
class Panel:
    """One video window: where it goes, what names it, and what fills it."""

    key: str
    label: str
    slot: str
    # Aperture this panel displays and its pixel aspect. A panel shows a whole
    # screen even when the encode inside it is smaller, so it is sized from the
    # aperture rather than the coded raster.
    aperture: tuple[int, int]
    par: tuple[int, int]
    # One line per entry. A single string in the profile becomes one line.
    spec: tuple[str, ...]
    # How the audio note refers to this panel, when the drawn label is too long
    # to sit inside a sentence. Defaults to the label.
    short_label: str | None
    placeholder: str | None
    # Footage. `path` is None until a recording exists.
    path: Path | None
    # Crop applied in the material's own pixels, as (x, y, width, height).
    crop: tuple[int, int, int, int] | None
    # Pad the material up to the aperture, as (width, height, x, y) in its own
    # pixels. Needed when the material is smaller than the aperture.
    pad: tuple[int, int, int, int] | None
    # Rate the material is re-timed to on input, when its stored rate is not
    # the rate the console displays it at.
    input_fps: str | None
    # How the material is scaled into its rectangle. Material already at the
    # console's own raster wants "neighbor": the panel is an enlargement of
    # real console pixels, and an interpolating filter would blend colours the
    # hardware never put next to each other, softening dither patterns that
    # are part of what the encode does. Anything else - a camera capture, a
    # source master far larger than its panel - is being reduced and wants the
    # default "lanczos".
    resize: str
    # Where the moving picture begins inside the material.
    fmv_start: float
    # Seconds of run-up before fmv_start that stay on the timeline.
    lead: float

    @property
    def display_aspect(self) -> float:
        """Width-to-height ratio of the aperture as it is meant to be seen."""
        width, height = self.aperture
        par_n, par_d = self.par
        return width * par_n / par_d / height

    @property
    def source_start(self) -> float:
        return self.fmv_start - self.lead

    @property
    def spec_depth(self) -> int:
        """Distance from the frame's bottom edge to the spec's last baseline."""
        return SPEC_GAP + (len(self.spec) - 1) * SPEC_LINE_HEIGHT


@dataclass(frozen=True)
class Comparison:
    """A profile's whole comparison specification."""

    profile: Path
    badge: str
    title: str
    audio_panel: str
    # Panel whose audio carries the run-up, before audio_panel's own panel
    # starts. None means audio_panel carries the whole video.
    audio_intro_panel: str | None
    # Whether the frame states which panel the audio comes from. Dropping the
    # note frees the height it and its gap occupy, which the panels take.
    show_audio_note: bool
    output: Path | None
    duration: float
    # Still, silent seconds appended after the picture ends, so YouTube's end
    # screen has somewhere to put its cards.
    tail_seconds: float
    panels: tuple[Panel, ...]

    def panel(self, key: str) -> Panel:
        return next(p for p in self.panels if p.key == key)

    @property
    def with_footage(self) -> list[Panel]:
        return [p for p in self.panels if p.path is not None]

    @property
    def picture_start(self) -> float:
        """Timeline second on which every panel begins moving."""
        return max(p.lead for p in self.panels)

    @property
    def audio_note(self) -> str:
        """The frame's statement of which panel the audio comes from."""
        panel = self.panel(self.audio_panel)
        return f"Audio: {panel.short_label or panel.label} only"

    @property
    def audio_switch(self) -> float | None:
        """Timeline second the audio hands over, or None if it never does.

        The hand-over is the moment the audio panel's own picture starts, so
        the run-up is heard from whichever panel is actually on screen for it.
        """
        if self.audio_intro_panel is None:
            return None
        return self.picture_start - self.panel(self.audio_panel).lead

    @property
    def bottom_baseline(self) -> int:
        """Baseline of the lowest text on the frame."""
        return CANVAS[1] - MARGIN - DESCENDER

    @property
    def arrangement(self) -> str:
        """Which slot arrangement this profile's panels form."""
        used = frozenset(p.slot for p in self.panels)
        for name, slots in LAYOUTS.items():
            if used == frozenset(slots):
                return name
        raise ValueError(
            f"{self.profile}: panels use slots {sorted(used)}, which is "
            f"no known arrangement: "
            + "; ".join(f"{n} needs {sorted(s)}" for n, s in LAYOUTS.items()))

    def _left_column(self) -> tuple[int, int, int, int, int]:
        """Return (main_bottom, main_height, main_width, right_left, width).

        The left column is the panel the video is about, so it takes all the
        height there is: its bottom edge follows back up from the lowest text on
        the frame, past however many spec lines stand between them, and its
        width follows from its aspect. The right column starts a gap past it, so
        enlarging the left one narrows the right instead of overlapping it.
        """
        main = {p.slot: p for p in self.panels}["main"]
        lowest = self.bottom_baseline
        if self.show_audio_note:
            lowest -= NOTE_GAP
        main_bottom = lowest - main.spec_depth
        main_height = main_bottom - PANEL_TOP
        main_width = round(main_height * main.display_aspect)
        right_left = MARGIN + main_width + COLUMN_GAP
        return (main_bottom, main_height, main_width, right_left,
                RIGHT_RIGHT - right_left)

    def _geometry_three(self) -> dict[str, int]:
        """Three panels: one large left, two stacked in the right column.

        The stack is what sets its own size. Two 4:3 screens one above the other
        are much taller than they are wide, so the height the left column leaves
        them decides the width, and that width is narrower than the column. The
        leftover is not padding to be removed: closing it would need the left
        panel taller than the canvas allows. The stack is pushed to the right
        edge instead, so its frames line up with each other and with the
        headline's right margin, and the slack reads as the gap between the two
        columns rather than as a hole beside them.
        """
        by_slot = {p.slot: p for p in self.panels}
        main = by_slot["main"]
        top, bottom = by_slot["right_top"], by_slot["right_bottom"]

        # Vertical first, because nothing horizontal can relax it: the left
        # column runs from the headline down to the lowest text on the frame.
        lowest = self.bottom_baseline
        if self.show_audio_note:
            lowest -= NOTE_GAP
        main_bottom = lowest - main.spec_depth
        main_height = main_bottom - PANEL_TOP
        main_width = round(main_height * main.display_aspect)

        # Both stacked rows share one height so their frames match; the upper
        # row's spec and the row gap stand between them, and the lower row's
        # bottom edge is flush with the left column's.
        stack_height = (main_height - top.spec_depth - ROW_GAP - LABEL_GAP) // 2
        if stack_height < 1:
            raise ValueError("the right column has no height left for two "
                             "stacked panels")
        stack_width = round(stack_height * max(top.display_aspect,
                                               bottom.display_aspect))

        # Two 4:3 screens stacked are far taller than wide, so their width is
        # narrower than a right column sized from a fixed page margin, and the
        # difference cannot be closed by shrinking anything: it would need the
        # left panel taller than the canvas allows. So the page margin is not
        # fixed here - it is whatever centres the content that the vertical
        # constraint produced. The slack becomes margin on both sides of the
        # frame instead of a hole beside the stack.
        content_width = main_width + COLUMN_GAP + stack_width
        margin = (CANVAS[0] - content_width) // 2
        if margin < MARGIN:
            raise ValueError(
                f"the content is {content_width}px wide, leaving only "
                f"{margin}px of margin against the {MARGIN}px minimum")
        right_edge = CANVAS[0] - margin
        return {
            "arrangement": 3,
            "margin": margin,
            "right_edge": right_edge,
            "content_width": content_width,
            "main_bottom": main_bottom,
            "main_height": main_height,
            "main_width": main_width,
            # The stack is flush right, so this gap also absorbs the rounding
            # left over from centring an odd-width content block.
            "column_gap": right_edge - stack_width - (margin + main_width),
            "stack_height": stack_height,
            "stack_width": stack_width,
            "top_spec_baseline": PANEL_TOP + stack_height + top.spec_depth,
            "bottom_top": main_bottom - stack_height,
        }

    def geometry(self) -> dict[str, int]:
        """The derived measurements the rectangles are built from."""
        if self.arrangement == "three":
            return self._geometry_three()
        by_slot = {p.slot: p for p in self.panels}

        main = by_slot["main"]
        # The left column's bottom edge follows back up from the lowest text on
        # the frame, past however many spec lines stand between them. With the
        # audio note dropped that lowest text is the spec itself, so the note's
        # own height and gap go to the panels.
        lowest = self.bottom_baseline
        if self.show_audio_note:
            lowest -= NOTE_GAP
        main_bottom = lowest - main.spec_depth
        main_height = main_bottom - PANEL_TOP
        main_width = round(main_height * main.display_aspect)
        # The right column starts a gap past the left one, so enlarging the
        # playback panel narrows this column instead of overlapping it.
        right_left = MARGIN + main_width + COLUMN_GAP
        right_width = RIGHT_RIGHT - right_left

        # The lower panel spans the right column exactly, so its frame lines up
        # with the row above it on both edges. Its height follows from that
        # width and its own aspect.
        lower_height = round(right_width
                             / by_slot["lower"].display_aspect)
        lower_top = main_bottom - lower_height

        # A row is as deep as its deepest spec, so a two-line spec in one panel
        # moves the row below for both.
        top_depth = max(by_slot["top_left"].spec_depth,
                        by_slot["top_right"].spec_depth)
        # The upper row takes the height that is left above the lower panel,
        # keeping that panel's label clear of the last spec line by the full row
        # gap. Deriving it this way means the gap is never what gets squeezed.
        top_height = (lower_top - LABEL_GAP - ROW_GAP - top_depth - PANEL_TOP)
        if top_height < 1:
            raise ValueError("the upper row has no height left; the lower "
                             "panel or the row gap is too large")
        top_spec_baseline = PANEL_TOP + top_height + top_depth

        # The two upper panels are justified to the column's outer edges, so
        # whatever their aspects leave over becomes the gap between them.
        inner_gap = right_width - sum(
            round(top_height * by_slot[slot].display_aspect)
            for slot in ("top_left", "top_right"))
        if inner_gap < INNER_GAP:
            raise ValueError(
                f"the upper row's panels leave only {inner_gap}px between "
                f"them, under the {INNER_GAP}px minimum")

        return {
            "arrangement": 4,
            "margin": MARGIN,
            "right_edge": RIGHT_RIGHT,
            "main_bottom": main_bottom,
            "inner_gap": inner_gap,
            "main_height": main_height,
            "main_width": main_width,
            "right_left": right_left,
            "right_width": right_width,
            "top_height": top_height,
            "top_spec_baseline": top_spec_baseline,
            "lower_height": lower_height,
            "lower_top": lower_top,
        }

    def rects(self) -> dict[str, tuple[int, int, int, int]]:
        """Each panel's video rectangle as (x, y, width, height)."""
        by_slot = {p.slot: p for p in self.panels}
        g = self.geometry()
        if self.arrangement == "three":
            top, bottom = by_slot["right_top"], by_slot["right_bottom"]
            top_w = round(g["stack_height"] * top.display_aspect)
            bottom_w = round(g["stack_height"] * bottom.display_aspect)
            return {
                by_slot["main"].key: (g["margin"], PANEL_TOP, g["main_width"],
                                      g["main_height"]),
                top.key: (g["right_edge"] - top_w, PANEL_TOP, top_w,
                          g["stack_height"]),
                bottom.key: (g["right_edge"] - bottom_w, g["bottom_top"],
                             bottom_w, g["stack_height"]),
            }
        rects: dict[str, tuple[int, int, int, int]] = {}

        rects[by_slot["main"].key] = (MARGIN, PANEL_TOP, g["main_width"],
                                      g["main_height"])

        left = by_slot["top_left"]
        right = by_slot["top_right"]
        left_w = round(g["top_height"] * left.display_aspect)
        right_w = round(g["top_height"] * right.display_aspect)
        rects[left.key] = (g["right_left"], PANEL_TOP, left_w, g["top_height"])
        rects[right.key] = (RIGHT_RIGHT - right_w, PANEL_TOP, right_w,
                            g["top_height"])

        # Exactly the column's width, so both its edges match the row above.
        rects[by_slot["lower"].key] = (g["right_left"], g["lower_top"],
                                       g["right_width"], g["lower_height"])

        return rects


def _pair(value: object, name: str, key: str, count: int) -> tuple[int, ...]:
    if (not isinstance(value, list) or len(value) != count
            or not all(isinstance(v, int) for v in value)):
        raise ValueError(
            f"[comparison.panels.{key}] {name} must be {count} integers")
    return tuple(value)


def load(profile_path: Path | str) -> Comparison:
    """Read a profile's [comparison] section.

    Validation lives here rather than in encode_config because this section's
    meaning - slots, apertures, synchronisation - belongs to the comparison
    frame, not to the encoder.
    """
    profile = load_profile(profile_path)
    data = profile.section("comparison")
    if not data:
        raise ValueError(f"{profile.path}: no [comparison] section")

    raw_panels = data.get("panels")
    if not isinstance(raw_panels, dict) or not raw_panels:
        raise ValueError(f"{profile.path}: [comparison.panels] must have "
                         f"at least one panel table")

    allowed = {"label", "short_label", "slot", "aperture", "pixel_aspect",
               "spec", "placeholder", "path", "crop", "pad", "input_fps",
               "resize", "fmv_start", "lead"}
    panels: list[Panel] = []
    for key, table in raw_panels.items():
        if not isinstance(table, dict):
            raise ValueError(
                f"[comparison.panels.{key}] must be a table")
        unknown = set(table) - allowed
        if unknown:
            raise ValueError(f"[comparison.panels.{key}] unknown keys: "
                             f"{', '.join(sorted(unknown))}")
        missing = {"label", "slot", "aperture", "pixel_aspect", "spec"} - set(table)
        if missing:
            raise ValueError(f"[comparison.panels.{key}] missing: "
                             f"{', '.join(sorted(missing))}")
        if table["slot"] not in SLOTS:
            raise ValueError(f"[comparison.panels.{key}] slot must be one of "
                             f"{', '.join(SLOTS)}")
        spec = table["spec"]
        if isinstance(spec, str):
            spec = (spec,)
        elif (isinstance(spec, list)
              and all(isinstance(line, str) for line in spec) and spec):
            spec = tuple(spec)
        else:
            raise ValueError(f"[comparison.panels.{key}] spec must be a "
                             f"string or a non-empty list of strings")
        resize = table.get("resize", "lanczos")
        if resize not in RESIZE_FILTERS:
            raise ValueError(
                f"[comparison.panels.{key}] resize must be one of "
                f"{', '.join(sorted(RESIZE_FILTERS))}")
        path = table.get("path")
        panels.append(Panel(
            key=key,
            label=table["label"],
            slot=table["slot"],
            aperture=_pair(table["aperture"], "aperture", key, 2),
            par=_pair(table["pixel_aspect"], "pixel_aspect", key, 2),
            spec=spec,
            short_label=table.get("short_label"),
            placeholder=table.get("placeholder"),
            path=(ROOT / path) if path else None,
            crop=(_pair(table["crop"], "crop", key, 4)
                  if "crop" in table else None),
            pad=(_pair(table["pad"], "pad", key, 4)
                 if "pad" in table else None),
            input_fps=table.get("input_fps"),
            resize=resize,
            fmv_start=float(table.get("fmv_start", 0.0)),
            lead=float(table.get("lead", 0.0)),
        ))

    used = [p.slot for p in panels]
    if len(set(used)) != len(used):
        raise ValueError(f"{profile.path}: two panels share one slot")
    # The slots used must form one whole arrangement: a missing slot would
    # leave a hole the geometry has no rule for.
    if frozenset(used) not in {frozenset(s) for s in LAYOUTS.values()}:
        raise ValueError(
            f"{profile.path}: panels use slots {sorted(set(used))}, which is "
            f"no known arrangement: "
            + "; ".join(f"{name} needs {sorted(slots)}"
                        for name, slots in LAYOUTS.items()))

    audio_panel = data.get("audio_panel")
    if audio_panel not in {p.key for p in panels}:
        raise ValueError(f"{profile.path}: audio_panel must name a panel")
    if next(p for p in panels if p.key == audio_panel).path is None:
        raise ValueError(f"{profile.path}: audio_panel {audio_panel!r} has "
                         f"no footage to take audio from")

    intro_panel = data.get("audio_intro_panel")
    if intro_panel is not None:
        if intro_panel not in {p.key for p in panels}:
            raise ValueError(f"{profile.path}: audio_intro_panel must name "
                             f"a panel")
        intro = next(p for p in panels if p.key == intro_panel)
        if intro.path is None:
            raise ValueError(f"{profile.path}: audio_intro_panel "
                             f"{intro_panel!r} has no footage")
        if intro.lead <= next(p for p in panels
                              if p.key == audio_panel).lead:
            raise ValueError(
                f"{profile.path}: audio_intro_panel {intro_panel!r} must "
                f"start before {audio_panel!r}, or it would never be heard")

    output = data.get("output")
    return Comparison(
        profile=Path(profile.path),
        badge=data.get("badge", ""),
        title=data.get("title", ""),
        audio_panel=audio_panel,
        audio_intro_panel=intro_panel,
        show_audio_note=bool(data.get("audio_note", True)),
        output=(ROOT / output) if output else None,
        duration=float(data.get("duration", 0.0)),
        tail_seconds=float(data.get("tail_seconds", 0.0)),
        panels=tuple(panels),
    )


def headline_width(spec: Comparison) -> int:
    """Drawn width of the badge and title, in pixels."""
    font = ImageFont.truetype(FONT_BOLD, TITLE_SIZE)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    width = round(draw.textlength(spec.title, font=font))
    if spec.badge:
        width += round(draw.textlength(spec.badge, font=font)) + BADGE_GAP
    return width


def check_headline(spec: Comparison) -> int:
    """Return the headline's width, refusing one wider than the frame.

    The headline shares the left edge of the panels below it, and the three
    arrangement centres those, so its room is whatever that centring leaves -
    a good deal less than the four arrangement's fixed page margin. Nothing
    else measures text, so without this a title simply runs off the canvas and
    only a rendered still shows it.
    """
    geometry = spec.geometry()
    room = geometry["right_edge"] - geometry["margin"]
    width = headline_width(spec)
    if width > room:
        raise ValueError(
            f"{spec.profile}: the headline is {width}px wide but only "
            f"{room}px is free between the margins; shorten it by "
            f"{width - room}px")
    return width


def layout(spec: Comparison) -> dict:
    """The layout as plain data, for the muxing stage and for review."""
    rects = spec.rects()
    return {
        "profile": str(spec.profile),
        "headline": " ".join(x for x in (spec.badge, spec.title) if x),
        "headline_width": check_headline(spec),
        "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
        "geometry": spec.geometry(),
        "picture_start": round(spec.picture_start, 6),
        "audio_panel": spec.audio_panel,
        "audio_note": spec.audio_note if spec.show_audio_note else None,
        "panels": [
            {
                "key": panel.key,
                "label": panel.label,
                "slot": panel.slot,
                "aperture": {"width": panel.aperture[0],
                             "height": panel.aperture[1]},
                "pixel_aspect": {"num": panel.par[0], "den": panel.par[1]},
                "display_aspect": round(panel.display_aspect, 6),
                "rect": {"x": rects[panel.key][0], "y": rects[panel.key][1],
                         "width": rects[panel.key][2],
                         "height": rects[panel.key][3]},
                "spec": list(panel.spec),
                "resize": panel.resize,
                "footage": str(panel.path) if panel.path else None,
                "source_start": round(panel.source_start, 6),
                "timeline_start": round(spec.picture_start - panel.lead, 6),
            }
            for panel in spec.panels
        ],
    }


def _fonts() -> dict[str, ImageFont.FreeTypeFont]:
    return {
        "title": ImageFont.truetype(FONT_BOLD, TITLE_SIZE),
        "label": ImageFont.truetype(FONT_BOLD, LABEL_SIZE),
        "spec": ImageFont.truetype(FONT_REGULAR, SPEC_SIZE),
        "note": ImageFont.truetype(FONT_REGULAR, NOTE_SIZE),
    }


def render(spec: Comparison, *, transparent_windows: bool) -> Image.Image:
    """Draw the frame.

    With `transparent_windows` the video rectangles are cleared to alpha 0 so
    the frame can be composited over the videos. Otherwise they are filled with
    a placeholder block, which is how a layout is reviewed before any footage
    exists.
    """
    check_headline(spec)
    image = Image.new("RGBA", CANVAS, BG)
    draw = ImageDraw.Draw(image)
    font = _fonts()
    margin = spec.geometry()["margin"]

    headline_x = margin
    if spec.badge:
        draw.text((headline_x, HEADLINE_BASELINE), spec.badge,
                  font=font["title"], fill=BADGE_FILL, anchor="ls")
        headline_x += round(draw.textlength(spec.badge, font=font["title"]))
        headline_x += BADGE_GAP
    draw.text((headline_x, HEADLINE_BASELINE), spec.title, font=font["title"],
              fill=TITLE_FILL, anchor="ls")
    if spec.show_audio_note:
        draw.text((margin, spec.bottom_baseline), spec.audio_note,
                  font=font["note"], fill=NOTE_FILL, anchor="ls")

    rects = spec.rects()
    for panel in spec.panels:
        x, y, w, h = rects[panel.key]

        draw.text((x, y - LABEL_GAP), panel.label, font=font["label"],
                  fill=LABEL_FILL, anchor="ls")
        for index, line in enumerate(panel.spec):
            draw.text((x, y + h + SPEC_GAP + index * SPEC_LINE_HEIGHT), line,
                      font=font["spec"], fill=SPEC_FILL, anchor="ls")

        # The stroke sits entirely outside the video rectangle so it never
        # covers a source pixel, and clearing the window cannot erase it.
        draw.rectangle(
            (x - STROKE_WIDTH, y - STROKE_WIDTH,
             x + w + STROKE_WIDTH - 1, y + h + STROKE_WIDTH - 1),
            outline=STROKE, width=STROKE_WIDTH)

        if transparent_windows:
            image.paste((0, 0, 0, 0), (x, y, x + w, y + h))
        else:
            image.paste(PLACEHOLDER, (x, y, x + w, y + h))
            caption = (panel.placeholder
                       or f"{panel.aperture[0]}×{panel.aperture[1]}")
            draw.text((x + w // 2, y + h // 2), caption, font=font["label"],
                      fill=PLACEHOLDER_TEXT, anchor="mm")

    return image


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path,
                        help="profile TOML carrying [comparison]")
    parser.add_argument("--overlay", type=Path,
                        help="write the RGBA overlay with cleared video "
                             "windows")
    parser.add_argument("--preview", type=Path,
                        help="write a standalone preview with placeholder "
                             "blocks instead of video windows")
    parser.add_argument("--json", type=Path,
                        help="write the layout for the mux stage")
    parser.add_argument("--print-layout", action="store_true",
                        help="print the layout to stdout")
    args = parser.parse_args()

    if not any((args.overlay, args.preview, args.json, args.print_layout)):
        parser.error("choose at least one of --overlay, --preview, --json, "
                     "--print-layout")

    spec = load(args.config)

    if args.overlay:
        render(spec, transparent_windows=True).save(args.overlay)
        print(f"overlay: {args.overlay}")
    if args.preview:
        render(spec, transparent_windows=False).save(args.preview)
        print(f"preview: {args.preview}")

    data = layout(spec)
    if args.json:
        args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2)
                             + "\n", encoding="utf-8")
        print(f"layout: {args.json}")
    if args.print_layout:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
