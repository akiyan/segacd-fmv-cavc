"""TTRC one-byte routing entry codec and current stream version."""

from __future__ import annotations

import operator


VERSION = 23
FEATURE_COLD_RUNS = 0x0001
FEATURE_FIXED_N = 0x0002
# Source compatibility for older tools/tests. The on-disc bit is unchanged;
# The on-disc bit retains the v16 interpretation of header vsync_n.
FEATURE_FIXED_N2 = FEATURE_FIXED_N
# 0x0004 was the removed optional-audio-codec flag. TTRC v17 is ADPCM-only.
FEATURE_PATTERN_SUPPLY = 0x0008
FEATURE_SHADOW_UPDATE_LISTS = 0x0010
FEATURE_VRAM_RAW_PREFETCH = 0x0020
FEATURE_DICBUF_INDEXED_RUNS = 0x0040
FEATURE_BOOT_VRAM_SIDECAR = 0x0080
FEATURE_WORDBUF_RING = 0x0100
SECTOR_BYTES = 2048
ROUTE_BYTES = 16 * 1024
# Compatibility name for callers that describe the allocation as a table.
TABLE_BYTES = ROUTE_BYTES
ENTRY_BYTES = 1
MAX_FRAMES = ROUTE_BYTES // ENTRY_BYTES
MAX_TABLE_SECTORS = ROUTE_BYTES // SECTOR_BYTES
FRAME_SECTORS = 5
CTRL_MASK = 0x07
CTRL_COUNT_MASK = 0x03
WORD4_FLAG = 0x04
MAX_CTRL_SECTORS = CTRL_COUNT_MASK
TOTAL_SHIFT = 3
WORD_SHIFT = 6
WORD_MASK = 0xC0
MAX_WORD_SECTORS = 4
MAX_ENTRY = (
    (3 << WORD_SHIFT)
    | (FRAME_SECTORS << TOTAL_SHIFT)
    | (WORD4_FLAG | 1)
)


def player_uses_packed_cold_runs(fps: float, features: int) -> bool:
    """Return whether the Sub player consumes the packed cold-run suffix.

    Dense 24/30fps streams use the suffix directly. Multi-source pattern
    supply also requires it at every rate. A lower-rate plain-Prg stream keeps
    the legacy entry-order walker so its frequent CDC polling remains intact.
    """
    return (
        float(fps) >= 24.0
        or bool(operator.index(features) & FEATURE_PATTERN_SUPPLY)
    )


def _index(value: object, name: str) -> int:
    try:
        return operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def encode_route(
    n_pay: object,
    n_ctrl: object,
    n_word: object = 0,
) -> int:
    """Encode one payload/control route and its WordBuf payload prefix."""
    pay = _index(n_pay, "n_pay")
    ctrl = _index(n_ctrl, "n_ctrl")
    word = _index(n_word, "n_word")
    total = pay + ctrl
    if pay < 0 or ctrl < 0 or word < 0:
        raise ValueError(
            "routing counts must be non-negative: "
            f"pay={pay}, ctrl={ctrl}, word={word}")
    if total > FRAME_SECTORS:
        raise ValueError(
            f"routing total {total} exceeds FRAME_SECTORS={FRAME_SECTORS}: "
            f"pay={pay}, ctrl={ctrl}")
    if ctrl > MAX_CTRL_SECTORS:
        raise ValueError(
            f"routing control {ctrl} exceeds "
            f"MAX_CTRL_SECTORS={MAX_CTRL_SECTORS}")
    if word > MAX_WORD_SECTORS or word > pay:
        raise ValueError(
            f"WordBuf payload prefix {word} is invalid for pay={pay}")
    ctrl_field = ctrl
    word_field = word
    if word == MAX_WORD_SECTORS:
        ctrl_field |= WORD4_FLAG
        word_field = 3
    return (
        (word_field << WORD_SHIFT)
        | (total << TOTAL_SHIFT)
        | ctrl_field
    )


def decode_route(entry: object) -> tuple[int, int, int]:
    """Decode and validate one packed entry as ``(pay, ctrl, total)``."""
    value = _index(entry, "routing entry")
    if not 0 <= value <= 0xFF:
        raise ValueError(f"routing entry is outside one byte: {value}")
    word = (value & WORD_MASK) >> WORD_SHIFT
    ctrl_field = value & CTRL_MASK
    ctrl = ctrl_field
    if ctrl_field & WORD4_FLAG:
        if word != 3:
            raise ValueError(
                f"routing WordBuf-4 escape lacks the 3-sector base: "
                f"0x{value:02X}")
        ctrl = ctrl_field & CTRL_COUNT_MASK
        word = MAX_WORD_SECTORS
    total = (value >> TOTAL_SHIFT) & CTRL_MASK
    if total > FRAME_SECTORS:
        raise ValueError(
            f"routing total {total} exceeds FRAME_SECTORS={FRAME_SECTORS}: "
            f"0x{value:02X}")
    if ctrl > total:
        raise ValueError(f"routing control {ctrl} exceeds total {total}: 0x{value:02X}")
    pay = total - ctrl
    if word > pay:
        raise ValueError(
            f"routing WordBuf prefix {word} exceeds payload {pay}: "
            f"0x{value:02X}")
    return pay, ctrl, total


def decode_word_sectors(entry: object) -> int:
    """Return the number of leading payload sectors staged to WordBuf."""
    value = _index(entry, "routing entry")
    pay, ctrl, _total = decode_route(value)
    ctrl_field = value & CTRL_MASK
    if ctrl_field & WORD4_FLAG:
        return MAX_WORD_SECTORS
    word = (value & WORD_MASK) >> WORD_SHIFT
    if word > pay or ctrl < 0:  # pragma: no cover - decode_route proved both
        raise AssertionError("decoded WordBuf prefix is inconsistent")
    return word


def routing_sector_count(nframes: object) -> int:
    """Return the exact packed table sector count for a valid frame count."""
    count = _index(nframes, "nframes")
    if not 1 <= count <= MAX_FRAMES:
        raise ValueError(f"nframes must be 1..{MAX_FRAMES}, got {count}")
    return (count + SECTOR_BYTES - 1) // SECTOR_BYTES


def validate_route_table(
    table: bytes | bytearray | memoryview,
    nframes: object,
    routing_sec: object,
) -> None:
    """Validate the complete sector-padded packed routing region."""
    count = _index(nframes, "nframes")
    expected_sec = routing_sector_count(count)
    sectors = _index(routing_sec, "routing_sec")
    if sectors != expected_sec:
        raise ValueError(
            f"routing_sec={sectors} does not match {count} frames ({expected_sec})")
    raw = bytes(table)
    expected_bytes = sectors * SECTOR_BYTES
    if len(raw) != expected_bytes:
        raise ValueError(
            f"routing region has {len(raw)} bytes, expected {expected_bytes}")
    if raw[0] != 0:
        raise ValueError(f"frame 0 routing entry must be zero, got 0x{raw[0]:02X}")
    for frame, entry in enumerate(raw[:count]):
        try:
            decode_route(entry)
        except ValueError as exc:
            raise ValueError(f"invalid routing entry at frame {frame}: {exc}") from exc
    if any(raw[count:]):
        raise ValueError("routing sector padding must be zero")
