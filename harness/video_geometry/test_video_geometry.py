#!/usr/bin/env python3
"""Small regression checks for the H40 source geometry helper."""

from tools.video_geometry import endpoint_snap_filter, geometry_plan, source_filter


def main() -> None:
    plan = geometry_plan(320, 224, 576, 400)
    assert plan["mode"] == "H40"
    assert plan["har"] == "32:35"
    assert plan["crop"] == [522, 400, 27, 0]
    assert plan["fit"] == "pad"
    assert plan["fit_size"] == [320, 202]
    # 320x224 with PAR 32:35 is the 64:49 visible NTSC aperture.
    assert abs(plan["display_aspect"] - 64 / 49) < 1e-12
    # A non-square source must be measured in displayed pixels, not coded pixels.
    ntsc = geometry_plan(320, 224, 640, 480, 8, 9)
    assert ntsc["crop"] == [640, 434, 0, 23]
    wide = geometry_plan(320, 224, 720, 480, 8, 9)
    assert wide["crop"] == [704, 480, 8, 0]
    vf = source_filter(320, 224, 576, 400)
    assert "scale=640:404" in vf and "pad=320:224" in vf
    assert source_filter(320, 224, 576, 400, fit="crop").startswith(
        "setsar=1,crop=522:400:27:0")
    direct_vf = source_filter(
        320, 224, 576, 400, denoise=False,
        resize_filter="lanczos")
    assert "hqdn3d" not in direct_vf and "gblur" not in direct_vf
    assert direct_vf.count("flags=lanczos") == 1
    assert "flags=area" in source_filter(
        320, 224, 576, 400, denoise=False,
        resize_filter="area")
    assert endpoint_snap_filter() == ""
    endpoint_vf = endpoint_snap_filter(2, 253)
    assert endpoint_vf.startswith("format=rgb24,lutrgb=")
    assert endpoint_vf.count(
        "if(lte(val,2),0,if(gte(val,253),255,val))") == 3
    try:
        endpoint_snap_filter(253, 2)
    except ValueError as exc:
        assert "black_max must be below" in str(exc)
    else:
        raise AssertionError("unordered endpoint snap limits were accepted")
    print("video geometry checks OK")


if __name__ == "__main__":
    main()
