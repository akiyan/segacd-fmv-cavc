"""Require existing short movies to retain every packed byte."""

import contextlib
import io
from unittest.mock import patch

import cavc_routing
import pack_stream
from harness.palette_capacity.test_fixture import PackedFixtureTestCase


class FrameCapacityPackingTests(PackedFixtureTestCase):
    def test_frame_cap_changes_no_bytes_for_an_existing_movie(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with patch.multiple(cavc_routing, ROUTE_BYTES=16384,
                                TABLE_BYTES=16384, MAX_FRAMES=16384,
                                MAX_TABLE_SECTORS=8), patch.object(
                                    pack_stream, "ROUTING_MAX_FRAMES", 16384):
                before = self.pack("frames16k", 64, fps=24)
            after = self.pack("frames65535", 64, fps=24)
        for name in ("HEADER.DAT", "BODY.DAT", "MOVIE.DAT", "paltab.bin", "palidx.bin"):
            with self.subTest(name=name):
                self.assertEqual((before / name).read_bytes(),
                                 (after / name).read_bytes())
