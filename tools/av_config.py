"""Single source of truth for the streaming geometry shared by the whole pipeline.

The encoder (``tools/sim.py``), the packer (``tools/pack_stream.py``) and the
on-disc player (``boot/movieplay_sp.s``) share one physical PrgBuf geometry.
Their objects are not identical: sim has a virtual quality budget, the packer
has an fps-derived normal prebuffer ceiling plus a physical delivery ceiling,
and the player holds the real sectors. Historically each side had its own
capacity knob:

* player  ``.equ RING_SIZE``       = 420 KB   (the physical buffer)
* pack    normal prebuffer ceiling  = fps-derived
* sim     quality budget             = 440 KB   (*larger than PrgBuf!*)

Three independent capacity values are a double-management trap: the sim can
borrow more virtual budget than the hardware can schedule, causing live
underruns even when the encode looked feasible.

Here we define the physical ring **once** and derive every capacity from it.
The exact schedule stays at or below the normal PrgBuf ceiling. The interval
above that ceiling is reserved entirely for live sector-arrival variation; the
encoder cannot spend it as ordinary future Supply. The reserve scales with the
time represented by one content frame: 20 KiB at 30 fps, 40 KiB at 15 fps,
and 25 KiB at 24 fps. The player's ``RING_SIZE`` is asserted equal to
``RING_SIZE_KB`` at build time (``tools/check_player_ring.py``, run by the
Makefile). Cold cap is supplied explicitly by the encode profile and passed
unchanged through the encoder, packer, and analysis renderer. The packer
refuses to re-cap an already encoded stream.
"""

import math
import os

# The outer boot image occupies the first 32 KiB of the data track. The BIOS
# supports a multi-sector Sub program; this project reserves its final 5 KiB at
# disc offset 0x6000 and loads it contiguously at Sub PRG 0x6000. Boot-only ISO
# directory scratch lives in the inactive timed-ring tail rather than directly
# after the program, so the resident image is not artificially capped at 4 KiB.
BOOT_IMAGE_BYTES = 0x00008000
SUB_BOOT_SOURCE_BASE = 0x00006000
SUB_BOOT_IMAGE_MAX_BYTES = 0x00001400
SUB_BOOT_EXTENSION_LOAD_BASE = 0x0007D260
SUB_BOOT_ISO_BUF_BASE = 0x00067000
SUB_BOOT_ISO_BUF_BYTES = 0x00010000
SUB_BOOT_ISO_BUF_END = SUB_BOOT_ISO_BUF_BASE + SUB_BOOT_ISO_BUF_BYTES

# Marker tests prove 0x7400..0x7FFF remains readable throughout continuous CD
# service. The live map combines that reclaimed resident tail with the existing
# 0x8000..0x97FF scratch: index/PCM/pending/LUT data stay below the BIOS-touched
# 0x9800 boundary, while the larger signed-delta table starts at 0xC000.
SUB_PRG_SAFE_BASE = 0x00007400
SUB_PRG_SAFE_END = 0x00009800
ADPCM_INDEX_TABLE_BASE = SUB_PRG_SAFE_BASE
ADPCM_INDEX_TABLE_BYTES = 0x00000B20
ADPCM_INDEX_TABLE_END = ADPCM_INDEX_TABLE_BASE + ADPCM_INDEX_TABLE_BYTES
PCM_DEC_BUF_BASE = 0x00008000
PCM_DEC_BUF_BYTES = 0x00000600
PCM_DEC_BUF_END = PCM_DEC_BUF_BASE + PCM_DEC_BUF_BYTES
ADPCM_OUTPUT_LUT_BASE = 0x00009600
ADPCM_OUTPUT_LUT_BYTES = 0x00000100
ADPCM_OUTPUT_LUT_END = ADPCM_OUTPUT_LUT_BASE + ADPCM_OUTPUT_LUT_BYTES
ADPCM_DELTA_TABLE_BASE = 0x0000C000
ADPCM_DELTA_TABLE_BYTES = 0x00001640
ADPCM_DELTA_TABLE_END = ADPCM_DELTA_TABLE_BASE + ADPCM_DELTA_TABLE_BYTES
SUB_BOOT_EXTENSION_EXEC_BASE = 0x00076800
SUB_BOOT_EXTENSION_MAX_BYTES = 0x000005A0
PRG_BUF_BASE = 0x0000D800

assert SUB_PRG_SAFE_BASE <= PCM_DEC_BUF_BASE
assert PCM_DEC_BUF_END <= SUB_PRG_SAFE_END
assert ADPCM_INDEX_TABLE_END <= PCM_DEC_BUF_BASE
assert ADPCM_OUTPUT_LUT_END <= SUB_PRG_SAFE_END
assert ADPCM_DELTA_TABLE_END <= PRG_BUF_BASE
assert (
    SUB_BOOT_SOURCE_BASE + SUB_BOOT_IMAGE_MAX_BYTES
    <= BOOT_IMAGE_BYTES)
assert SUB_BOOT_ISO_BUF_END <= 0x00077000

# Physical PRG-RAM ring in the player. MUST equal boot/movieplay_sp.s
# `.equ RING_SIZE` (0x69000 = 420 KB). Build-time assertion enforces it.
# The 2 KiB reduction gives the signed ADPCM delta table a checked gap before
# the ring without consuming either pending-sector scratch or APPLY space.
RING_SIZE_KB = 420

# The route format can represent four Word sectors for compatibility, but the
# live PRG-RAM map intentionally has three pending destinations.
WORD_PENDING_SECTORS = 3

# Keep the physical overflow guard distinct from delivery-jitter headroom. The
# player throttles its CD pump at RING_SIZE-4KB (back-pressure). The encoder's
# exact schedule stops at the fps-derived normal ceiling, leaving the complete
# cadence reserve for live sector-arrival variation. DELIVERY_CAP_KB is the
# upper observation boundary one sector below back-pressure, not encoder
# Supply.
RING_PHYSICAL_GUARD_KB = 4
RING_DELIVERY_GUARD_KB = 2
RING_JITTER_REFERENCE_FPS = 30.0
RING_JITTER_REFERENCE_KB = 20

# Frame 0 is staged only during boot and may span the jitter tail plus the
# otherwise-unused APPLY ring. It is not part of the timed PrgBuf occupancy.
FRAME0_PATTERN_STAGING_KB = 36

# Derived fixed physical limits — do not set these independently anywhere else.
BACKPRESSURE_KB = RING_SIZE_KB - RING_PHYSICAL_GUARD_KB
DELIVERY_CAP_KB = BACKPRESSURE_KB - RING_DELIVERY_GUARD_KB


def _nominal_content_fps(fps):
    """Normalize NTSC-like profile rates to their named content cadence."""
    value = float(fps)
    if value <= 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    nearest = round(value)
    if nearest > 0 and math.isclose(
            value, nearest, rel_tol=0.0, abs_tol=0.1):
        return float(nearest)
    return value


def cadence_jitter_reserve_kb(fps):
    """Return the fps-scaled normal-cap reserve rounded up to a whole KiB."""
    nominal_fps = _nominal_content_fps(fps)
    nominal_kb = (
        RING_JITTER_REFERENCE_KB
        * RING_JITTER_REFERENCE_FPS
        / nominal_fps
    )
    return int(math.ceil(nominal_kb))


def prg_buf_cap_kb(fps):
    """Return the normal PrgBuf/prebuffer ceiling below physical jitter."""
    cap = DELIVERY_CAP_KB - cadence_jitter_reserve_kb(fps)
    if cap <= 0:
        raise ValueError(
            f"fps {fps!r} requires all {DELIVERY_CAP_KB} KiB of PrgBuf "
            "for delivery jitter")
    return cap


def quality_budget_kb(fps):
    """Keep offline time-shifting within the normal fps-specific PrgBuf."""
    return prg_buf_cap_kb(fps)


def scheduled_delivery_cap_kb(fps):
    """Return the encoder's fps-derived scheduled occupancy ceiling.

    Planned delivery must not consume the live jitter reserve. Keeping this
    equal to the normal PrgBuf ceiling makes the shared-sector planner reject
    excess Supply before image decisions rather than relying on a later
    hardware overrun or per-profile cold-cap adjustment.
    """
    return prg_buf_cap_kb(fps)


def ring_jitter_headroom_kb(fps):
    """Return live arrival headroom above the scheduled PrgBuf ceiling."""
    return DELIVERY_CAP_KB - scheduled_delivery_cap_kb(fps)


# Compatibility aliases are the 30 fps reference values. Runtime encode, pack,
# player constants, analysis, and HUD gates must call the fps-aware functions.
RING_JITTER_HEADROOM_KB = ring_jitter_headroom_kb(30)
RING_CAP_KB = prg_buf_cap_kb(30)
PRG_BUF_CAP_KB = RING_CAP_KB
QUALITY_BUDGET_KB = quality_budget_kb(30)

assert DELIVERY_CAP_KB - RING_CAP_KB == RING_JITTER_HEADROOM_KB

# A CRAM epoch change rebuilds the visible picture under a newly selected
# palette. Inspect this many frames starting at each switch and give only the
# highest predicted Miss-risk frame priority over later quality reserves.
# Physical sector, cold, PrgBuf, and jitter limits remain authoritative.
CRAM_QUALITY_PRIORITY_SEARCH_FRAMES = 4

# --- Fixed encoder/player resources ---
# The resident movie-pattern pool starts at tile 1 and ends immediately before
# the fixed HUD font at VRAM 0xD000. The single movie name table starts at
# 0xE000, so DEBUG and release builds share the same contiguous pool.
VRAM_PATTERN_BASE_TILE = 1
VRAM_HUD_FONT_TILE = 0xD000 // 32
VRAM_MOVIE_NT_TILE = 0xE000 // 32
VRAM_FIRST_MOVIE_NT_TILE = VRAM_MOVIE_NT_TILE
VRAM_PATTERN_POOL_TILES = (
    VRAM_HUD_FONT_TILE - VRAM_PATTERN_BASE_TILE)

# These are pipeline policy, not per-source choices.  Forward fill uses safe
# physical-slot padding for future Prg payload, while startup audio is clamped
# later to the decoded chunk size and wave-RAM capacity.
PACK_FORWARD_FILL = True
STARTUP_AUDIO_PREFETCH_FRAMES = 30

# Palette algorithm parameters are fixed across sources.  Only the algorithm
# name remains a TOML choice.
PALETTE_MAP_WEIGHT = 1.0
PALETTE_SEAM_WEIGHT = 8.0
PALETTE_SEAM_ITERATIONS = 2
PALETTE_SAMPLE_COUNTS = (120, 240, 480)
PALETTE_VALIDATE_FRAMES = 120
PALETTE_SEGMENT_TRAIN_FRAMES = 240
PALETTE_SEGMENT_VALIDATE_FRAMES = 60
PALETTE_SEGMENT_GAIN_RELATIVE = 0.005
PALETTE_SEGMENT_GAIN_PER_PIXEL = 0.002

# --- CRAM pre-load table (PALTAB) and switch table (PALIDX) capacity ---
# Both tables are build-time static data embedded in the Main-IP player image
# (pack writes paltab.bin / palidx.bin beside the split stream and
# boot/movieplay_ip.s incbins them into its transient .startup section).  The
# player copies them into the fixed Main-RAM map (M-PALTAB / M-PALIDX) before
# codegen reuses .startup, so CRAM data and switch timing are fully
# independent of stream delivery (slip/recovery safe) and no palette bytes
# exist in HEADER.DAT or BODY.DAT.
# Capacity = Main-RAM table size = PALTAB_MAX_SEG * 128 bytes (16 -> 2 KB at
# PALTAB_RAM 0xFFB200..0xFFBA00). Keep this constant and the player equ equal
# (build-checked by tools/check_player_ring.py).  The 16-segment cap is a
# fixed Main-RAM map decision; the encoder merges detected palette ranges
# down to it (quality trade accepted).
PALTAB_MAX_SEG = 16
# The fixed 24 KiB boot stage right after the header keeps its header-field
# name (paltab_sec) but now carries only the optional boot-VRAM sidecar
# records; palette data does not ride the disc.
PALTAB_STAGE_KB = 24
# PALIDX: 16 entries * 4 bytes: up to PALTAB_MAX_SEG-1 (frame.u16,
# segment.u16) switches followed by a 0xFFFF frame sentinel; unused entries
# repeat the sentinel.
PALIDX_ENTRIES = 16
PALIDX_BYTES = PALIDX_ENTRIES * 4
PALIDX_FRAME_SENTINEL = 0xFFFF
BOOT_VRAM_SIDECAR_ENTRY_BYTES = 34  # slot.u16 + packed 32-byte pattern
BOOT_VRAM_REGION_A_BYTES = 0x0F00   # bank +0x0000..+0x0F00
BOOT_VRAM_REGION_B_BYTES = 0x2000   # bank +0x1000..+0x3000
BOOT_VRAM_REGION_C_BYTES = 0x1000   # bank +0x5000..+0x6000


def boot_vram_sidecar_capacity():
    """Records preserved around the directory in BOOT_STAGE (fixed regions)."""
    entry = BOOT_VRAM_SIDECAR_ENTRY_BYTES
    return (
        BOOT_VRAM_REGION_A_BYTES // entry
        + BOOT_VRAM_REGION_B_BYTES // entry
        + BOOT_VRAM_REGION_C_BYTES // entry
    )

assert PALTAB_MAX_SEG <= PALIDX_ENTRIES, (
    "PALIDX must hold one entry per palette switch plus the sentinel")

# --- Content timing shared by sim and pack ---
# SEGA-CD 1x is the codec's physical delivery source.  The encoder's fresh
# per-frame quality allowance is derived from these constants; it is not a
# profile bitrate setting.
CD_SECTOR_BYTES = 2048
CD_SECTORS_PER_SECOND = 75
CD_BYTES_PER_SECOND = CD_SECTOR_BYTES * CD_SECTORS_PER_SECOND

# The player is synchronized by an explicit VBlank cadence when the rate has a
# qualified schedule. Integer NTSC divisors use one repeated interval, while
# named 24 fps content alternates two and three VBlanks. Keep this decision in
# one place so display pacing, CD deadlines, and fixed PCM chunks cannot drift.
NTSC_VSYNC = 60_000 / 1001
_INTEGER_VBLANK_TOLERANCE = 0.01
# Fixed display pacing is currently practical through N=4.  Larger intervals
# would regularly need more than the routing format's five useful sectors per
# frame and can outlive the Main CPU's 12-bit stopwatch cadence window.
MAX_FIXED_VBLANK_INTERVAL = 4

# RF5C164 phase-step conversion.  One output sample advances the 11-bit
# frequency delta once per 384 clocks of the 12.5 MHz PCM clock.
RF5C164_CLOCK_HZ = 12_500_000
RF5C164_DIVIDER = 384
RF5C164_FD_SCALE = 0x800


def vsync_n_for_fps(fps):
    """Nearest integer VBlank interval used as the player's cadence hint."""
    value = float(fps)
    if value <= 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    return max(1, int(round(NTSC_VSYNC / value)))


def playback_fps_for_content(fps):
    """Effective long-term playback rate for audio chunk sizing.

    Qualified VBlank rates use the exact NTSC-derived cadence. Other rates use
    the requested content rate and remain delivery-paced.
    """
    value = float(fps)
    cadence = vblank_cadence_pattern(value)
    if cadence is not None:
        return NTSC_VSYNC * len(cadence) / sum(cadence)
    return value


def rf5c164_fd(samples_per_frame, playback_fps):
    """Return the RF5C164 frequency delta matching one fixed audio chunk.

    Matching the player's actual fixed chunk rate matters more than matching
    the nominal source rate after the packer has evenly retimed the source.
    Otherwise the wave-RAM lead slowly walks into a re-sync threshold.
    """
    rate = int(samples_per_frame) * float(playback_fps)
    if rate <= 0:
        raise ValueError(
            f"audio chunk rate must be positive, got {samples_per_frame!r} * "
            f"{playback_fps!r}")
    fd = round(rate / (RF5C164_CLOCK_HZ / RF5C164_DIVIDER) * RF5C164_FD_SCALE)
    if not 0 < fd <= 0xFFFF:
        raise ValueError(f"RF5C164 frequency delta is out of range: {fd}")
    return fd


def fixed_vblank_interval(fps):
    """Return the authoritative fixed-N interval, or ``None``.

    Rates close to an integer NTSC VBlank divisor use that exact display
    cadence.  Delivery-paced rates such as 24 fps return ``None`` even though
    their nearest interval hint is also N=2.
    """
    value = float(fps)
    if value <= 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    n = vsync_n_for_fps(value)
    if not 1 <= n <= MAX_FIXED_VBLANK_INTERVAL:
        return None
    if abs((NTSC_VSYNC / value) - n) > _INTEGER_VBLANK_TOLERANCE:
        return None
    return n


def uses_fixed_n_cadence(fps):
    """Whether the stream uses its header's exact fixed-N VBlank cadence."""
    return fixed_vblank_interval(fps) is not None


def uses_fixed_n2_cadence(fps):
    """Compatibility helper for callers that specifically need N=2."""
    return fixed_vblank_interval(fps) == 2


def vblank_cadence_pattern(fps):
    """Return the authoritative repeating VBlank intervals, or ``None``.

    Frame 1 uses element zero, frame 2 uses element one, and the pattern then
    repeats. Named 24 fps content uses ``(2, 3)`` for an exact long-term
    24000/1001 fps display rate. Unqualified rates remain delivery-paced.
    """
    value = float(fps)
    if value <= 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    fixed_n = fixed_vblank_interval(value)
    if fixed_n is not None:
        return (fixed_n,)
    if _nominal_content_fps(value) == 24.0:
        return (2, 3)
    return None


def uses_vblank_cadence(fps):
    """Whether the stream has an authoritative repeating VBlank schedule."""
    return vblank_cadence_pattern(fps) is not None


def fixed_cd_sector_rate(vsync_n):
    """Return reduced CD-1x sectors/frame for one fixed VBlank interval."""
    n = int(vsync_n)
    if not 1 <= n <= MAX_FIXED_VBLANK_INTERVAL:
        raise ValueError(
            f"fixed VBlank interval must be 1..{MAX_FIXED_VBLANK_INTERVAL}, "
            f"got {vsync_n!r}")
    # 75 sectors/s * N * (1001/60000)s = 1001*N/800 sectors/frame.
    numerator = 1001 * n
    modulus = 800
    divisor = math.gcd(numerator, modulus)
    return numerator // divisor, modulus // divisor


def cd_sector_rate_steps(fps):
    """Return per-cadence-step CD numerators and their shared modulus.

    Each VBlank supplies 1001/800 of a CD sector. A periodic display cadence
    therefore needs a periodic physical-deadline accumulator too; replacing a
    2/3 pattern with its average would overfund the first short interval.
    """
    value = float(fps)
    if value <= 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    cadence = vblank_cadence_pattern(value)
    if cadence is not None:
        numerators = tuple(1001 * interval for interval in cadence)
        modulus = 800
        divisor = modulus
        for numerator in numerators:
            divisor = math.gcd(divisor, numerator)
        return (
            tuple(numerator // divisor for numerator in numerators),
            modulus // divisor,
        )
    nominal = int(round(value))
    if nominal <= 0:
        raise ValueError(f"fps must round to a positive integer, got {fps!r}")
    return (75,), nominal


def cd_sector_rate(fps):
    """Return the long-term average CD sectors per movie frame.

    Use :func:`cd_sector_rate_steps` for deadline construction. The average is
    retained for diagnostics and callers that do not construct frame slots.
    """
    numerators, modulus = cd_sector_rate_steps(fps)
    if len(numerators) == 1:
        return numerators[0], modulus
    numerator = sum(numerators)
    denominator = modulus * len(numerators)
    divisor = math.gcd(numerator, denominator)
    return numerator // divisor, denominator // divisor


def audio_frame_samples(fps, audio_rate):
    """Fixed mono samples per frame, rounded up to avoid underrun."""
    return int(math.ceil(int(audio_rate) / playback_fps_for_content(fps)))


IMA_CHECKPOINT_BYTES = 4


def adpcm_frame_samples(fps, audio_rate=22_050):
    """Fixed decoded samples per IMA chunk, rounded up to an even count."""
    count = audio_frame_samples(fps, audio_rate)
    return count + (count & 1)


def audio_frame_layout(fps):
    """Return the ADPCM ``(rate, decoded_samples, control_bytes)`` layout."""
    samples = adpcm_frame_samples(fps, 22_050)
    return 22_050, samples, IMA_CHECKPOINT_BYTES + samples // 2

# --- Realized cold matches the sim and never exceeds the cap ---
# The sim (tools/sim.py) and the pack (tools/pack_stream.py) now share ONE tile-slot
# allocator (tools/tile_alloc.py, two-pass contiguous). So the pack's realized
# per-frame cold equals the sim's selected cold, not necessarily the cap itself.
# The historical +overhead (the sim modelled LRU residency while the pack
# allocated contiguously and re-loaded a few tiles) is gone: the two-pass
# protects every reuse tile shown this frame before allocating cold slots, so
# nothing is re-loaded. There is therefore no separate realized ceiling and no
# per-source `CBRSIM_COLD_CAP_REALIZED` env override. The pack still asserts
# realized <= cap as a guard. frame0 (the full-load header) is exempt.

# --- Per-frame cold cap supplied by the encode profile ---
# A profile supplies either one scalar cap ("225") or, for a multi-interval
# VBlank cadence such as 24 fps, one cap per display interval ("2:170,3:250"
# maps a 2-VBlank slot to 170 cold patterns and a 3-VBlank slot to 250).
def _parse_cold_cap_spec(requested_cap=None):
    """Return the cap spec as ``{vblank_interval_or_None: cap}``.

    A scalar spec is stored under the key ``None`` and applies to every frame.
    """
    raw_cap = (
        os.environ.get("CBRSIM_COLD_CAP", "").strip()
        if requested_cap is None
        else requested_cap
    )
    if raw_cap in (None, ""):
        raise ValueError(
            "cold cap is required; set [encoder].cold_cap in the profile")
    if isinstance(raw_cap, bool):
        raise ValueError(f"profile cold cap must be an integer: {raw_cap!r}")
    if isinstance(raw_cap, str) and ":" in raw_cap:
        spec = {}
        for entry in raw_cap.split(","):
            entry = entry.strip()
            if not entry:
                raise ValueError(
                    f"profile cold cap has an empty entry: {raw_cap!r}")
            interval_text, _, cap_text = entry.partition(":")
            try:
                interval = int(interval_text)
                cap = int(cap_text)
            except ValueError as exc:
                raise ValueError(
                    "profile cold cap entries must be "
                    f"'vblanks:cap' integers: {entry!r}") from exc
            if not 1 <= interval <= MAX_FIXED_VBLANK_INTERVAL:
                raise ValueError(
                    "cold cap VBlank interval must be within "
                    f"1..{MAX_FIXED_VBLANK_INTERVAL}: {entry!r}")
            if cap <= 0:
                raise ValueError(
                    f"profile cold cap must be positive: {entry!r}")
            if interval in spec:
                raise ValueError(
                    f"duplicate cold cap interval {interval}: {raw_cap!r}")
            spec[interval] = cap
        return spec
    try:
        effective_cap = int(raw_cap)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"profile cold cap must be an integer: {raw_cap!r}") from exc
    if effective_cap <= 0:
        raise ValueError(
            f"profile cold cap must be positive: {effective_cap}")
    return {None: effective_cap}


def cold_cap(requested_cap=None):
    """Return the largest explicit positive cold cap of the spec.

    ``requested_cap`` is used by frozen-log consumers such as the packer.
    Otherwise ``CBRSIM_COLD_CAP`` is the internal handoff populated from the
    required ``[encoder].cold_cap`` profile key.  For a per-interval spec this
    is the capacity-reservation ceiling; per-frame limits come from
    ``frame_cold_caps``.
    """
    return max(_parse_cold_cap_spec(requested_cap).values())


def cold_cap_spec(requested_cap=None):
    """Return the canonical cold cap spec string ("225" or "2:170,3:250")."""
    spec = _parse_cold_cap_spec(requested_cap)
    if set(spec) == {None}:
        return str(spec[None])
    return ",".join(
        f"{interval}:{spec[interval]}" for interval in sorted(spec))


def cold_cap_key(requested_cap=None):
    """Return the filesystem-safe cap identity used in artifact names."""
    return cold_cap_spec(requested_cap).replace(":", "x").replace(",", "-")


def frame_cold_caps(frame_count, fps, requested_cap=None):
    """Return the per-frame cold cap list for one encode.

    Frame 1 uses cadence element zero, matching the CD-deadline accumulator
    (``stream_schedule.rate_deltas``): a frame's cap belongs to the display
    slot whose VBlanks fund its delivery and decode.  Frame 0 is the untimed
    full load and carries the reservation ceiling only.
    """
    count = int(frame_count)
    if count <= 0:
        raise ValueError(f"frame count must be positive, got {frame_count!r}")
    spec = _parse_cold_cap_spec(requested_cap)
    if set(spec) == {None}:
        return [spec[None]] * count
    cadence = vblank_cadence_pattern(fps)
    if cadence is None:
        raise ValueError(
            "a per-interval cold cap spec needs a qualified VBlank cadence; "
            f"fps={fps!r} is delivery-paced")
    missing = sorted(set(cadence) - set(spec))
    if missing:
        raise ValueError(
            f"cold cap spec lacks caps for VBlank intervals {missing} "
            f"used by the {fps!r} fps cadence")
    unused = sorted(interval for interval in spec if interval not in cadence)
    if unused:
        raise ValueError(
            f"cold cap spec names VBlank intervals {unused} that the "
            f"{fps!r} fps cadence never uses")
    caps = [max(spec.values())]
    caps.extend(
        spec[cadence[(frame - 1) % len(cadence)]]
        for frame in range(1, count))
    return caps


def cold_realized_ceiling(requested_cap=None):
    """Pack-time realized-cold ceiling. Now == the cap: the shared two-pass allocator
    makes the pack's realized cold equal the sim's cap exactly, so the ceiling is the
    cap itself (the assert `realized <= ceiling` holds by construction)."""
    return cold_cap(requested_cap)
