import struct
import tempfile
import unittest
from pathlib import Path

import player_constants
import cavc_routing
import pattern_supply
import av_config


def make_header(*, mode=av_config.DISPLAY_MODE_BYTE, fps=30, features=None,
                audio_bytes=None, audio_fd=0x345,
                supply_counts=(0, 0, 0), pool=1400, base=1,
                tcols=None, trows=28, cold_cap=190):
    if features is None:
        features = cavc_routing.FEATURE_COLD_RUNS
        if av_config.uses_vblank_cadence(fps):
            features |= cavc_routing.FEATURE_VBLANK_CADENCE
    if tcols is None:
        tcols = av_config.SCREEN_COLS
    cells = tcols * trows
    frames = 2714
    if audio_bytes is None:
        audio_bytes = {15: 1472, 24: 920, 30: 736}.get(fps, 736)
    prefix = struct.pack(
        ">4s8H4LBB3L6H",
        b"CAVC", frames, tcols, trows, cells,
        pool, base, cavc_routing.FRAME_SECTORS, 13,
        12416, cavc_routing.routing_sector_count(frames), 194, 12416,
        mode, 0, 2, 14, av_config.PALTAB_STAGE_KB * 1024 // 2048,
        av_config.vsync_n_for_fps(fps),
        audio_bytes, fps, audio_fd, 30, features,
    )
    sector = bytearray(prefix + bytes(130) + bytes(player_constants.SECTOR - 192))
    if features & cavc_routing.FEATURE_PATTERN_SUPPLY:
        wr0, wr1, dic = supply_counts
        layout = pattern_supply.word_ram_layout(frames, cells, cold_cap)
        player_constants.PATTERN_SUPPLY_STRUCT.pack_into(
            sector, player_constants.PATTERN_SUPPLY_OFFSET,
            player_constants.PATTERN_SUPPLY_MAGIC,
            player_constants.PATTERN_SUPPLY_VERSION, 0,
            wr0, wr1, dic,
            (wr0 + 63) // 64, (wr1 + 63) // 64, (dic + 63) // 64,
            cold_cap,
            layout.wr0_load_bytes, layout.wr1_load_bytes,
        )
    return player_constants.stamp_header_sector(sector)


class PlayerConstantsTest(unittest.TestCase):
    def test_pool_may_fill_up_to_the_hud_font(self):
        # The single NT starts at 0xE000, so the pool may fill every tile below
        # the fixed font at tile 1744 (base 1 + 1743).
        values = player_constants.parse_header_sector(make_header(pool=1743))
        self.assertEqual(values.pool, 1743)
        self.assertEqual(values.font_vtile, 0xDA00 // 32)
        self.assertEqual(values.font_addr, 0xDA00)

        with self.assertRaisesRegex(ValueError, "overlaps"):
            player_constants.parse_header_sector(make_header(pool=1744))

    def test_full_aperture_30fps_current_values(self):
        values = player_constants.parse_header_sector(make_header())
        self.assertEqual(values.bmbytes, 140)
        self.assertEqual(values.col0, 0)
        self.assertEqual(values.row0, 0)
        self.assertEqual(values.vbudget, 3200)
        self.assertEqual(values.audio_bytes, 736)
        self.assertEqual(values.audio_fd, 0x345)
        self.assertEqual(values.body_arm_sec, 46)
        self.assertEqual((values.sec_num, values.sec_mod), (1001, 400))
        self.assertEqual((values.sec_base, values.sec_rem), (2, 201))
        self.assertEqual(values.cadence_period, 1)
        self.assertEqual(values.vsync_alt, 2)
        self.assertEqual((values.sec_alt_base, values.sec_alt_rem), (2, 201))
        self.assertEqual(values.pump_mask, 0x03FF)
        self.assertEqual(values.wave_pump_mask, 0x01FF)

    def test_h40_15fps_uses_fixed_n4_sector_accumulator(self):
        values = player_constants.parse_header_sector(
            make_header(
                fps=15,
                features=(cavc_routing.FEATURE_COLD_RUNS
                          | cavc_routing.FEATURE_VBLANK_CADENCE)))
        self.assertEqual(values.screen_cols, 40)
        self.assertEqual(values.vsync_n, 4)
        self.assertEqual(values.vbudget, 3200)
        self.assertEqual(values.audio_bytes, 1472)
        self.assertEqual((values.sec_num, values.sec_mod), (1001, 200))
        self.assertEqual((values.sec_base, values.sec_rem), (5, 1))
        self.assertEqual(values.pump_mask, 0x003F)
        self.assertEqual(values.wave_pump_mask, 0x00FF)
        self.assertEqual(values.prg_buf_cap_patterns, 374 * 1024 // 32)
        self.assertEqual(values.prg_delivery_cap_patterns, 374 * 1024 // 32)
        self.assertEqual(values.jitter_headroom_kb, 40)

    def test_24fps_uses_two_three_vblank_sector_steps(self):
        values = player_constants.parse_header_sector(make_header(fps=24))
        self.assertEqual(values.vsync_n, 2)
        self.assertEqual(values.vsync_alt, 3)
        self.assertEqual(values.cadence_period, 2)
        self.assertEqual((values.sec_num, values.sec_mod), (2002, 800))
        self.assertEqual((values.sec_base, values.sec_rem), (2, 402))
        self.assertEqual(values.sec_alt_num, 3003)
        self.assertEqual((values.sec_alt_base, values.sec_alt_rem), (3, 603))
        self.assertEqual(values.audio_bytes, 920)

    def test_h40_centers_a_36x25_stream_without_expanding_its_grid(self):
        values = player_constants.parse_header_sector(
            make_header(tcols=36, trows=25))
        self.assertEqual((values.tcols, values.trows, values.cells), (36, 25, 900))
        self.assertEqual((values.screen_cols, values.screen_rows), (40, 28))
        self.assertEqual((values.col0, values.row0), (2, 1))
        self.assertEqual(values.bmbytes, 113)

    def test_scroll_requires_full_h40_lists_and_pattern_supply(self):
        base = (
            cavc_routing.FEATURE_COLD_RUNS
            | cavc_routing.FEATURE_VBLANK_CADENCE
            | cavc_routing.FEATURE_PATTERN_SUPPLY
            | cavc_routing.FEATURE_DICBUF_INDEXED_RUNS
            | cavc_routing.FEATURE_SHADOW_UPDATE_LISTS
            | cavc_routing.FEATURE_SCROLL
        )
        values = player_constants.parse_header_sector(make_header(
            fps=24, features=base,
            supply_counts=(880, 880, 256),
        ))
        self.assertTrue(values.features & cavc_routing.FEATURE_SCROLL)
        letterboxed = player_constants.parse_header_sector(make_header(
            fps=24, trows=18, features=base,
            supply_counts=(880, 880, 256),
        ))
        self.assertTrue(letterboxed.features & cavc_routing.FEATURE_SCROLL)
        self.assertEqual((letterboxed.col0, letterboxed.row0), (0, 5))
        for kwargs, message in (
            ({"tcols": 36, "features": base}, "full-width 40-column"),
            ({"features": base & ~cavc_routing.FEATURE_SHADOW_UPDATE_LISTS},
             "update lists"),
            ({"features": base & ~cavc_routing.FEATURE_PATTERN_SUPPLY},
             "pattern supply"),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                    ValueError, message):
                player_constants.parse_header_sector(make_header(
                    fps=24, supply_counts=(880, 880, 256), **kwargs))

    def test_removed_vertical_scroll_bit_is_reserved(self):
        with self.assertRaisesRegex(ValueError, "reserved feature bits"):
            player_constants.parse_header_sector(make_header(
                features=(cavc_routing.FEATURE_COLD_RUNS
                          | 0x0400)))

    def test_prg_jitter_constants_follow_content_fps(self):
        expected = {
            15: (374, 374, 40),
            24: (389, 389, 25),
            30: (394, 394, 20),
        }
        for fps, (normal_kb, delivery_kb, jitter_kb) in expected.items():
            with self.subTest(fps=fps):
                values = player_constants.parse_header_sector(
                    make_header(fps=fps))
                self.assertEqual(
                    values.prg_buf_cap_patterns, normal_kb * 1024 // 32)
                self.assertEqual(
                    values.prg_delivery_cap_patterns, delivery_kb * 1024 // 32)
                self.assertEqual(values.jitter_headroom_kb, jitter_kb)

    def test_changed_fixed_header_rejects_stale_signature(self):
        sector = bytearray(make_header())
        sector[54:56] = struct.pack(">H", 445)
        with self.assertRaisesRegex(ValueError, "signature"):
            player_constants.parse_header_sector(bytes(sector))

    def test_magic_is_identifying_data_not_a_player_parser_guard(self):
        sector = bytearray(make_header())
        sector[:4] = b"TTRC"
        self.assertEqual(
            player_constants.parse_header_sector(bytes(sector)).frames, 2714)

    def test_legacy_layout_is_bounded_without_a_magic_guard(self):
        prefix = struct.pack(
            ">4s9H4LBB3L6H",
            b"TTRC", 25, 2714, 32, 28, 896, 1400, 1,
            cavc_routing.FRAME_SECTORS, 13,
            12416, 2, 194, 12416,
            0, 0, 2, 14, av_config.PALTAB_STAGE_KB * 1024 // 2048,
            2, 736, 30, 0x345, 30,
            cavc_routing.FEATURE_COLD_RUNS,
        )
        sector = bytearray(
            prefix + bytes(128) + bytes(player_constants.SECTOR - 192))
        sector = player_constants.stamp_header_sector(sector)
        with self.assertRaises(ValueError) as caught:
            player_constants.parse_header_sector(sector)
        self.assertNotIn("magic", str(caught.exception).lower())

    def test_rejects_noncanonical_boot_stage_size(self):
        sector = bytearray(make_header())
        sector[46:50] = struct.pack(">L", 1)
        sector = player_constants.stamp_header_sector(sector)
        with self.assertRaisesRegex(ValueError, "fixed boot-stage size"):
            player_constants.parse_header_sector(sector)

    def test_adpcm_derives_control_and_table_sizes(self):
        values = player_constants.parse_header_sector(make_header(
            features=(cavc_routing.FEATURE_COLD_RUNS
                      | cavc_routing.FEATURE_VBLANK_CADENCE),
            audio_bytes=736,
        ))
        self.assertEqual(values.audio_bytes, 736)
        self.assertEqual(values.audio_control_bytes, 372)
        self.assertEqual(values.adpcm_table_sectors, 5)

    def test_removed_audio_feature_bit_is_reserved(self):
        with self.assertRaisesRegex(ValueError, "reserved feature bits"):
            player_constants.parse_header_sector(make_header(
                features=(cavc_routing.FEATURE_COLD_RUNS | 0x0004),
            ))

    def test_pattern_supply_extension(self):
        layout = pattern_supply.word_ram_layout(
            frames=2714, cells=40 * 28, cold_cap=190)
        values = player_constants.parse_header_sector(make_header(
            features=(cavc_routing.FEATURE_COLD_RUNS
                      | cavc_routing.FEATURE_VBLANK_CADENCE
                      | cavc_routing.FEATURE_PATTERN_SUPPLY
                      | cavc_routing.FEATURE_DICBUF_INDEXED_RUNS),
            supply_counts=(
                layout.wr0_patterns, layout.wr1_patterns,
                pattern_supply.DIC_BUF_PATTERNS),
        ))
        self.assertEqual(values.wr0_patterns, layout.wr0_patterns)
        self.assertEqual(values.wr1_patterns, layout.wr1_patterns)
        self.assertEqual(values.dic_patterns, pattern_supply.DIC_BUF_PATTERNS)
        self.assertEqual((values.wr0_sectors, values.wr1_sectors, values.dic_sectors),
                         ((layout.wr0_patterns + 63) // 64,
                          (layout.wr1_patterns + 63) // 64,
                          (pattern_supply.DIC_BUF_PATTERNS + 63) // 64))
        self.assertEqual(values.routing_bytes, 4096)
        self.assertEqual(values.routing_offset, layout.routing_offset)
        self.assertEqual(values.wr0_offset, layout.wr0_offset)
        self.assertEqual(values.wr0_end, layout.wr0_end)
        self.assertEqual(values.wr0_capacity, layout.wr0_patterns)
        self.assertEqual(values.wr1_offset, layout.wr1_offset)
        self.assertEqual(values.wr1_capacity, layout.wr1_patterns)

    def test_pattern_supply_uses_fixed_n4_and_low_rate_polls_at_15fps(self):
        values = player_constants.parse_header_sector(make_header(
            fps=15,
            features=(cavc_routing.FEATURE_COLD_RUNS
                      | cavc_routing.FEATURE_VBLANK_CADENCE
                      | cavc_routing.FEATURE_PATTERN_SUPPLY
                      | cavc_routing.FEATURE_DICBUF_INDEXED_RUNS),
            supply_counts=(880, 880, 256),
            cold_cap=360,
        ))
        self.assertEqual((values.sec_num, values.sec_mod), (1001, 200))
        self.assertEqual(values.pump_mask, 0x003F)
        self.assertEqual(values.wave_pump_mask, 0x00FF)
        self.assertEqual(values.wr0_patterns, 880)
        self.assertEqual(values.wr1_patterns, 880)

    def test_vblank_cadence_rejects_a_stale_vsync_hint(self):
        header = bytearray(make_header(fps=15))
        header[50:52] = struct.pack(">H", 2)
        header = player_constants.stamp_header_sector(header)
        with self.assertRaisesRegex(ValueError, "VBlank-cadence header"):
            player_constants.parse_header_sector(header)

    def test_pattern_supply_requires_indexed_dicbuf_feature(self):
        with self.assertRaisesRegex(ValueError, "indexed DicBuf"):
            player_constants.parse_header_sector(make_header(
                features=(cavc_routing.FEATURE_COLD_RUNS
                          | cavc_routing.FEATURE_VBLANK_CADENCE
                          | cavc_routing.FEATURE_PATTERN_SUPPLY),
                supply_counts=(1, 1, 1),
            ))

    def test_generation_is_deterministic_and_preserves_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            header = Path(td) / "HEADER.DAT"
            output = Path(td) / "player_constants.inc"
            header.write_bytes(make_header())
            player_constants.generate_include(header, output)
            first = output.read_bytes()
            first_mtime = output.stat().st_mtime_ns
            player_constants.generate_include(header, output)
            self.assertEqual(output.read_bytes(), first)
            self.assertEqual(output.stat().st_mtime_ns, first_mtime)
            text = first.decode()
            self.assertIn(".equ PC_AUDIO_BYTES, 0x02E0", text)
            self.assertIn(".equ PC_AUDIO_CONTROL_BYTES, 0x0174", text)
            self.assertIn(".equ PC_AUDIO_FD, 0x0345", text)
            self.assertIn(".equ PC_BODY_ARM_SEC, 0x002E", text)
            self.assertIn(".equ PC_SEC_REM, 0x00C9", text)
            self.assertIn(
                ".equ PC_PRG_BUF_CAP_PATTERNS, 0x3140", text)
            self.assertIn(
                ".equ PC_PRG_DELIVERY_CAP_PATTERNS, 0x3140", text)
            self.assertIn(".equ PC_JITTER_HEADROOM_KB, 0x0014", text)


if __name__ == "__main__":
    unittest.main()
