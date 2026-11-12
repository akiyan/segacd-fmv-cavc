"""Construction-time publication reservation for the existing player."""

import av_config

POLICY = "singleton-publication-reserve-v1"
RUN_SETUP_WORDS = 96
PATTERN_WORDS = 16


def display_words(cols, rows, *, scroll_build=False, vertical=False, cram=False):
    """Reserve the DEBUG-compatible NT, scroll, HUD, CPU and CRAM bundle."""
    words = (int(rows) - 1) * 64 + int(cols)
    if scroll_build:
        words = (32 if vertical else int(rows)) * 64 + 16
    return words + 52 + 512 + (256 if cram else 0)


def pattern_limit(cols, rows, **display):
    """Bound any later Prg/Wr/Dic fragmentation, including WordBuf wrap.

    Source selection happens after placement. Each cold tail pattern can
    become its own run, so reserve one setup per pattern rather than assuming
    adjacent destinations will remain one physical source span.
    """
    remaining = av_config.VBLANK_DMA_WORDS - display_words(cols, rows, **display)
    if remaining < 0:
        raise ValueError("display publication alone exceeds the VBlank budget")
    return min(av_config.FINAL_VBLANK_TILES,
               remaining // (PATTERN_WORDS + RUN_SETUP_WORDS))


def verify_runs(runs, cols, rows, **display):
    """Check the final realized source runs before marking an encode complete."""
    tail = [run for run in runs if run[0] >= av_config.FINAL_VBLANK_SLOT]
    cost = (display_words(cols, rows, **display)
            + sum(run[1] for run in tail) * PATTERN_WORDS
            + len(tail) * RUN_SETUP_WORDS)
    if cost > av_config.VBLANK_DMA_WORDS:
        raise ValueError(f"final-VBlank bundle costs {cost}/3200 units")
    return cost
