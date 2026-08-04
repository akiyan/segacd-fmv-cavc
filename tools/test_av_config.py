#!/usr/bin/env python3
"""Regression tests for shared playback timing, ADPCM sizing, and cold caps."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import av_config


class RingGeometryTests(unittest.TestCase):
    def test_sub_boot_and_adpcm_hot_data_use_only_verified_prg(self) -> None:
        self.assertEqual(av_config.BOOT_IMAGE_BYTES, 0x08000)
        self.assertEqual(av_config.SUB_BOOT_SOURCE_BASE, 0x06000)
        self.assertEqual(av_config.SUB_BOOT_IMAGE_MAX_BYTES, 0x01400)
        self.assertEqual(av_config.SUB_BOOT_EXTENSION_LOAD_BASE, 0x7D260)
        self.assertEqual(av_config.SUB_BOOT_ISO_BUF_BASE, 0x67000)
        self.assertEqual(av_config.SUB_BOOT_ISO_BUF_BYTES, 0x10000)
        self.assertEqual(av_config.SUB_BOOT_ISO_BUF_END, 0x77000)
        self.assertEqual(av_config.SUB_PRG_SAFE_BASE, 0x07400)
        self.assertEqual(av_config.SUB_PRG_SAFE_END, 0x09800)
        self.assertEqual(av_config.PCM_DEC_BUF_BASE, 0x08000)
        self.assertEqual(av_config.PCM_DEC_BUF_BYTES, 0x0600)
        self.assertEqual(av_config.PCM_DEC_BUF_END, 0x08600)
        self.assertEqual(av_config.ADPCM_INDEX_TABLE_BASE, 0x07400)
        self.assertEqual(av_config.ADPCM_INDEX_TABLE_BYTES, 0x0B20)
        self.assertEqual(av_config.ADPCM_INDEX_TABLE_END, 0x07F20)
        self.assertEqual(av_config.ADPCM_OUTPUT_LUT_BASE, 0x09600)
        self.assertEqual(av_config.ADPCM_OUTPUT_LUT_BYTES, 0x0100)
        self.assertEqual(av_config.ADPCM_OUTPUT_LUT_END, 0x09700)
        self.assertEqual(av_config.ADPCM_DELTA_TABLE_BASE, 0x0C000)
        self.assertEqual(av_config.ADPCM_DELTA_TABLE_BYTES, 0x01640)
        self.assertEqual(av_config.ADPCM_DELTA_TABLE_END, 0x0D640)
        self.assertEqual(av_config.SUB_BOOT_EXTENSION_EXEC_BASE, 0x76800)
        self.assertEqual(av_config.SUB_BOOT_EXTENSION_MAX_BYTES, 0x05A0)
        self.assertEqual(av_config.PRG_BUF_BASE, 0x0D800)

    def test_full_reclaimed_ring_geometry(self) -> None:
        self.assertEqual(av_config.RING_SIZE_KB, 420)
        self.assertEqual(av_config.WORD_PENDING_SECTORS, 3)
        self.assertEqual(av_config.RING_PHYSICAL_GUARD_KB, 4)
        self.assertEqual(av_config.RING_DELIVERY_GUARD_KB, 2)
        self.assertEqual(av_config.RING_JITTER_HEADROOM_KB, 20)
        self.assertEqual(av_config.FRAME0_PATTERN_STAGING_KB, 36)
        self.assertEqual(av_config.RING_CAP_KB, 394)
        self.assertEqual(av_config.PRG_BUF_CAP_KB, 394)
        self.assertEqual(av_config.QUALITY_BUDGET_KB, 394)
        self.assertEqual(av_config.BACKPRESSURE_KB, 416)
        self.assertEqual(av_config.DELIVERY_CAP_KB, 414)
        self.assertEqual(
            av_config.DELIVERY_CAP_KB - av_config.RING_CAP_KB, 20)

    def test_jitter_reserve_scales_with_frame_interval(self) -> None:
        self.assertEqual(av_config.cadence_jitter_reserve_kb(30), 20)
        self.assertEqual(av_config.cadence_jitter_reserve_kb(24), 25)
        self.assertEqual(av_config.cadence_jitter_reserve_kb(15), 40)
        self.assertEqual(av_config.prg_buf_cap_kb(30), 394)
        self.assertEqual(av_config.prg_buf_cap_kb(24), 389)
        self.assertEqual(av_config.prg_buf_cap_kb(15), 374)
        expected = {
            15: (374, 40),
            24: (389, 25),
            30: (394, 20),
        }
        for fps, (delivery_kb, headroom_kb) in expected.items():
            self.assertEqual(
                av_config.scheduled_delivery_cap_kb(fps), delivery_kb)
            self.assertEqual(
                av_config.ring_jitter_headroom_kb(fps), headroom_kb)
            self.assertEqual(
                av_config.scheduled_delivery_cap_kb(fps)
                + av_config.ring_jitter_headroom_kb(fps),
                av_config.DELIVERY_CAP_KB,
            )

    def test_ntsc_like_rates_use_named_content_cadence(self) -> None:
        self.assertEqual(
            av_config.cadence_jitter_reserve_kb(30_000 / 1001), 20)
        self.assertEqual(
            av_config.cadence_jitter_reserve_kb(24_000 / 1001), 25)
        self.assertEqual(
            av_config.scheduled_delivery_cap_kb(15_000 / 1001), 374)

    def test_fixed_encoder_and_pack_resources(self) -> None:
        self.assertEqual(av_config.VRAM_PATTERN_BASE_TILE, 1)
        self.assertEqual(av_config.VRAM_FIRST_MOVIE_NT_TILE, 1792)
        self.assertEqual(av_config.VRAM_MOVIE_NT_TILE, 1792)
        self.assertEqual(av_config.VRAM_PATTERN_POOL_TILES, 1743)
        self.assertEqual(av_config.VRAM_HUD_FONT_TILE, 1744)
        self.assertTrue(av_config.PACK_FORWARD_FILL)
        self.assertEqual(av_config.STARTUP_AUDIO_PREFETCH_FRAMES, 30)

    def test_boot_sidecar_capacity_preserves_fixed_word_ram_holes(self) -> None:
        # v25: segment palettes ride the player image, so the three preserved stage
        # holes are fixed and the capacity is segment-independent:
        # 0x0F00//34 + 0x2000//34 + 0x1000//34 = 112 + 240 + 120 records.
        self.assertEqual(av_config.boot_vram_sidecar_capacity(), 472)


class PlaybackTimingTests(unittest.TestCase):
    def test_cd_1x_physical_constants(self) -> None:
        self.assertEqual(av_config.CD_SECTOR_BYTES, 2048)
        self.assertEqual(av_config.CD_SECTORS_PER_SECOND, 75)
        self.assertEqual(av_config.CD_BYTES_PER_SECOND, 153_600)

    def test_ntsc_integer_vblank_rates_keep_existing_chunks(self) -> None:
        self.assertEqual(av_config.vsync_n_for_fps(15), 4)
        self.assertAlmostEqual(av_config.playback_fps_for_content(15), 15_000 / 1001)
        self.assertEqual(av_config.adpcm_frame_samples(15), 1472)
        self.assertEqual(av_config.audio_frame_layout(15), (22_050, 1472, 740))

        self.assertEqual(av_config.vsync_n_for_fps(30), 2)
        self.assertAlmostEqual(av_config.playback_fps_for_content(30), 30_000 / 1001)
        self.assertEqual(av_config.adpcm_frame_samples(30), 736)
        self.assertEqual(av_config.audio_frame_layout(30), (22_050, 736, 372))

    def test_24fps_uses_the_exact_two_three_vblank_pattern(self) -> None:
        self.assertEqual(av_config.vsync_n_for_fps(24), 2)
        self.assertAlmostEqual(
            av_config.playback_fps_for_content(24), 24_000 / 1001)
        self.assertEqual(av_config.adpcm_frame_samples(24), 920)
        self.assertEqual(av_config.audio_frame_layout(24), (22_050, 920, 464))
        self.assertFalse(av_config.uses_fixed_n_cadence(24))
        self.assertTrue(av_config.uses_vblank_cadence(24))
        self.assertEqual(av_config.vblank_cadence_pattern(24), (2, 3))
        self.assertEqual(
            av_config.vblank_cadence_pattern(24_000 / 1001), (2, 3))

    def test_integer_ntsc_divisors_use_fixed_cadence(self) -> None:
        self.assertEqual(av_config.fixed_vblank_interval(15), 4)
        self.assertTrue(av_config.uses_fixed_n_cadence(15))
        self.assertEqual(av_config.fixed_vblank_interval(30), 2)
        self.assertTrue(av_config.uses_fixed_n2_cadence(30))
        self.assertTrue(av_config.uses_fixed_n2_cadence(30_000 / 1001))
        self.assertFalse(av_config.uses_fixed_n2_cadence(15))
        self.assertEqual(av_config.fixed_vblank_interval(60), 1)
        self.assertTrue(av_config.uses_fixed_n_cadence(60))
        self.assertIsNone(av_config.fixed_vblank_interval(24))

    def test_30fps_cd_rate_matches_two_ntsc_vblanks(self) -> None:
        numerator, modulus = av_config.cd_sector_rate(30)
        self.assertEqual((numerator, modulus), (1001, 400))
        acc = 0
        deltas = []
        for _ in range(400):
            acc += numerator
            delta, acc = divmod(acc, modulus)
            deltas.append(delta)
        self.assertEqual(sum(deltas), 1001)
        self.assertEqual(deltas.count(2), 199)
        self.assertEqual(deltas.count(3), 201)
        self.assertEqual(acc, 0)

    def test_15fps_cd_rate_matches_four_ntsc_vblanks(self) -> None:
        numerator, modulus = av_config.cd_sector_rate(15)
        self.assertEqual((numerator, modulus), (1001, 200))
        acc = 0
        deltas = []
        for _ in range(200):
            acc += numerator
            delta, acc = divmod(acc, modulus)
            deltas.append(delta)
        self.assertEqual(sum(deltas), 1001)
        self.assertEqual(deltas.count(5), 199)
        self.assertEqual(deltas.count(6), 1)
        self.assertEqual(acc, 0)

    def test_24fps_cd_rate_preserves_each_two_three_vblank_deadline(self) -> None:
        self.assertEqual(av_config.cd_sector_rate_steps(24), ((2002, 3003), 800))
        self.assertEqual(av_config.cd_sector_rate(24), (1001, 320))

    def test_near_30_but_non_ntsc_rate_stays_delivery_paced(self) -> None:
        self.assertFalse(av_config.uses_fixed_n_cadence(29.8))
        self.assertFalse(av_config.uses_vblank_cadence(29.8))
        self.assertEqual(av_config.cd_sector_rate_steps(29.8), ((75,), 30))
        self.assertEqual(av_config.cd_sector_rate(29.8), (75, 30))

    def test_invalid_fps_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            av_config.vsync_n_for_fps(0)
        with self.assertRaises(ValueError):
            av_config.cd_sector_rate(0)
        with self.assertRaises(ValueError):
            av_config.fixed_cd_sector_rate(5)


class ColdCapTests(unittest.TestCase):
    def test_explicit_profile_cap_is_returned_unchanged(self) -> None:
        self.assertEqual(av_config.cold_cap(180), 180)
        self.assertEqual(av_config.cold_cap(200), 200)
        self.assertEqual(av_config.cold_cap(480), 480)

    def test_profile_environment_is_the_runtime_handoff(self) -> None:
        with patch.dict(os.environ, {"CBRSIM_COLD_CAP": "210"}, clear=True):
            self.assertEqual(av_config.cold_cap(), 210)
            self.assertEqual(av_config.cold_realized_ceiling(), 210)

    def test_missing_or_invalid_cap_is_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "cold cap is required"):
                av_config.cold_cap()
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "must be positive"):
                av_config.cold_cap(value)
        for value in (True, "1.5"):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "must be an integer"):
                av_config.cold_cap(value)

    def test_pack_ceiling_uses_the_same_explicit_cap(self) -> None:
        self.assertEqual(av_config.cold_realized_ceiling(180), 180)
        self.assertEqual(av_config.cold_realized_ceiling(225), 225)

    def test_interval_spec_parses_and_reports_the_ceiling(self) -> None:
        self.assertEqual(av_config.cold_cap("2:170,3:250"), 250)
        self.assertEqual(av_config.cold_cap_spec("3:250, 2:170"), "2:170,3:250")
        self.assertEqual(av_config.cold_cap_spec(225), "225")
        self.assertEqual(av_config.cold_cap_key("2:170,3:250"), "2x170-3x250")
        self.assertEqual(av_config.cold_cap_key("225"), "225")

    def test_interval_spec_rejects_bad_entries(self) -> None:
        for value in ("2:170,2:250", "0:100", "5:100", "2:0", "2:a", "2:"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                av_config.cold_cap(value)

    def test_frame_cold_caps_follow_the_24fps_cadence(self) -> None:
        caps = av_config.frame_cold_caps(6, 24, "2:170,3:250")
        # Frame 1 uses cadence element zero (2 VBlanks), like rate_deltas.
        self.assertEqual(caps, [250, 170, 250, 170, 250, 170])
        self.assertEqual(
            av_config.frame_cold_caps(4, 30, 200), [200, 200, 200, 200])

    def test_frame_cold_caps_reject_mismatched_cadence(self) -> None:
        with self.assertRaisesRegex(ValueError, "delivery-paced"):
            av_config.frame_cold_caps(4, 26, "2:170,3:250")
        with self.assertRaisesRegex(ValueError, "lacks caps"):
            av_config.frame_cold_caps(4, 24, "2:170")
        with self.assertRaisesRegex(ValueError, "never uses"):
            av_config.frame_cold_caps(4, 30, "2:170,3:250")
        with self.assertRaisesRegex(ValueError, "must be positive"):
            av_config.frame_cold_caps(0, 24, "2:170,3:250")


if __name__ == "__main__":
    unittest.main()
