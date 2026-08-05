#!/usr/bin/env python3
"""Source-to-Mega-Drive geometry helpers.

The codec outputs the H40 raster: 320 pixels wide with HAR/PAR 32:35, which
describes a 64:49 visible NTSC aperture when 224 lines are shown.  The default
``pad`` fit preserves every source pixel; ``crop`` is an explicit, HAR-aware
object-fit-cover conversion that fills the output raster and may discard active
pixels at the source edges.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess

MODE_NAME = "H40"
HAR_NUM = 32
HAR_DEN = 35
HAR = HAR_NUM / HAR_DEN
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 224
RESIZE_FILTERS = {"area", "bicubic", "bilinear", "lanczos", "neighbor"}


def display_aspect(width: int, height: int) -> float:
    return (width / height) * HAR


def parse_ratio(value: str | None) -> tuple[int, int]:
    if not value or value in {"N/A", "0:1"}:
        return 1, 1
    num, den = value.split(":", 1)
    return int(num), int(den)


def endpoint_snap_filter(black_max: int = -1, white_min: int = 256) -> str:
    """Build an RGB source filter that snaps only values near the endpoints."""
    if black_max < 0 and white_min > 255:
        return ""
    if not 0 <= black_max <= 255 or not 0 <= white_min <= 255:
        raise ValueError("endpoint snap limits must be within 0..255")
    if black_max >= white_min:
        raise ValueError("endpoint snap black_max must be below white_min")
    expr = f"if(lte(val,{black_max}),0,if(gte(val,{white_min}),255,val))"
    return f"format=rgb24,lutrgb=r='{expr}':g='{expr}':b='{expr}'"


def probe_source(src: str) -> tuple[int, int, int, int]:
    """Return coded width/height and the source sample-aspect ratio."""
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,sample_aspect_ratio", "-of", "json", src],
        text=True,
    )
    stream = json.loads(out)["streams"][0]
    sar_num, sar_den = parse_ratio(stream.get("sample_aspect_ratio"))
    return int(stream["width"]), int(stream["height"]), sar_num, sar_den


def probe_size(src: str) -> tuple[int, int]:
    """Return the first video stream's coded width and height."""
    width, height, _, _ = probe_source(src)
    return width, height


def _even(value: int) -> int:
    return max(2, value - (value & 1))


def center_crop(src_w: int, src_h: int, target_dar: float,
                src_sar: float = 1.0) -> tuple[int, int, int, int]:
    """Return an even centre crop matching target_dar after source SAR."""
    src_dar = (src_w / src_h) * src_sar
    if src_dar > target_dar + 1e-9:
        crop_h = src_h
        crop_w = _even(math.floor(src_h * target_dar / src_sar))
        crop_w = min(crop_w, src_w)
        return crop_w, crop_h, (src_w - crop_w) // 2, 0
    if src_dar < target_dar - 1e-9:
        crop_w = src_w
        crop_h = _even(math.floor(src_w * src_sar / target_dar))
        crop_h = min(crop_h, src_h)
        return crop_w, crop_h, 0, (src_h - crop_h) // 2
    return _even(src_w), _even(src_h), 0, 0


def geometry_plan(width: int, height: int, src_w: int, src_h: int,
                  src_sar_num: int = 1, src_sar_den: int = 1,
                  fit: str = "pad") -> dict:
    if fit not in {"pad", "crop"}:
        raise ValueError("fit must be pad or crop")
    dar = display_aspect(width, height)
    src_sar = src_sar_num / src_sar_den
    cw, ch, cx, cy = center_crop(src_w, src_h, dar, src_sar)
    src_dar = (src_w / src_h) * src_sar
    if src_dar > dar:
        fit_w = width
        fit_h = _even(math.floor(width * HAR / src_dar))
    else:
        fit_h = height
        fit_w = _even(math.floor(height * src_dar / HAR))
    return {
        "mode": MODE_NAME,
        "har": f"{HAR_NUM}:{HAR_DEN}",
        "src": [src_w, src_h],
        "src_sar": f"{src_sar_num}:{src_sar_den}",
        "crop": [cw, ch, cx, cy],
        "fit": fit,
        "fit_size": [fit_w, fit_h],
        "out": [width, height],
        "display_aspect": dar,
    }


def source_filter(width: int, height: int, src_w: int, src_h: int,
                  *, src_sar_num: int = 1, src_sar_den: int = 1,
                  fit: str = "pad",
                  denoise: bool = True,
                  resize_filter: str = "lanczos") -> str:
    """Build the canonical ffmpeg filter, accounting for source SAR."""
    resize_filter = resize_filter.lower()
    if resize_filter not in RESIZE_FILTERS:
        raise ValueError(
            f"unsupported resize filter {resize_filter!r}; "
            f"choose {', '.join(sorted(RESIZE_FILTERS))}")
    p = geometry_plan(width, height, src_w, src_h,
                      src_sar_num, src_sar_den, fit)
    cw, ch, cx, cy = p["crop"]
    fw, fh = p["fit_size"]
    if fit == "crop":
        vf = ["setsar=1", f"crop={cw}:{ch}:{cx}:{cy}"]
        # The crop already has the displayed aspect after HAR.
        # Scale it to the complete coded raster: this is object-fit: cover,
        # not merely removal of black source margins.
        iw, ih = width, height
        current_w, current_h = cw, ch
    else:
        # Normalize source SAR, then scale the complete source to the largest
        # raster with the output's displayed aspect. Padding never drops source
        # pixels; crop remains an explicit opt-in.
        vf = ["setsar=1"]
        iw, ih = fw, fh
        current_w, current_h = src_w, src_h
    if denoise:
        # Keep the source's displayed shape during the denoise pass. Scaling
        # to the MD raster before cropping/padding would apply the HAR twice.
        vf += [f"scale={iw * 2}:{ih * 2}:flags={resize_filter}",
               "hqdn3d=6:6:8:8", "gblur=sigma=1.6"]
        current_w, current_h = iw * 2, ih * 2
    if (current_w, current_h) != (iw, ih):
        vf.append(f"scale={iw}:{ih}:flags={resize_filter}")
    if fit == "pad":
        vf.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    return ",".join(vf)


def raw_filter(width: int, height: int, src_w: int, src_h: int,
               *, src_sar_num: int = 1, src_sar_den: int = 1,
               fit: str = "pad",
               resize_filter: str = "lanczos") -> str:
    return source_filter(width, height, src_w, src_h,
                         src_sar_num=src_sar_num, src_sar_den=src_sar_den,
                         fit=fit,
                         denoise=False,
                         resize_filter=resize_filter)


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True)
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--fit", choices=("pad", "crop"), default="pad")
    ap.add_argument("--resize-filter", choices=sorted(RESIZE_FILTERS), default="lanczos")
    ap.add_argument("--no-master-denoise", action="store_true")
    ap.add_argument("--source-sar", help="override input SAR, e.g. 25:27 for a 576x400 file intended as 4:3")
    args = ap.parse_args()
    w = args.width or DEFAULT_WIDTH
    h = args.height or DEFAULT_HEIGHT
    sw, sh, sar_num, sar_den = probe_source(args.src)
    if args.source_sar:
        sar_num, sar_den = parse_ratio(args.source_sar)
    p = geometry_plan(w, h, sw, sh, sar_num, sar_den, args.fit)
    p["master_vf"] = source_filter(w, h, sw, sh,
                                   src_sar_num=sar_num, src_sar_den=sar_den,
                                   fit=args.fit,
                                   denoise=not args.no_master_denoise,
                                   resize_filter=args.resize_filter)
    p["raw_vf"] = raw_filter(w, h, sw, sh,
                             src_sar_num=sar_num, src_sar_den=sar_den,
                             fit=args.fit,
                             resize_filter=args.resize_filter)
    print(json.dumps(p, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
