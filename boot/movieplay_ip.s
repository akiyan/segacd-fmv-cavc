/*
 * Phase B3: delta stream player - Main (IP) side (ダブルバッファ, tearing除去)。
 *
 * タイルプールは単一の永続VRAM領域(両ネームテーブルが共有, B1のLRUで表示中slotは
 * 上書きされないことが保証済み)。ネームテーブルは2枚(NT0=0xC000, NT1=0xE000)を
 * 交互に使う。Main RAM に shadow[576](cell->entry) を持ち:
 *   1. n_load 個のタイルを slot へ書込(共有プール)
 *   2. n_upd をシャドウに反映 shadow[cell]=entry
 *   3. シャドウ全体(576)を「裏」ネームテーブルへ blit (裏は非表示なので安全)
 *   4. VBlank で reg2 を裏へ flip(原子的) → tearing無し
 * これで「前フレーム差分の追いつき」不要(裏は常に完全な現フレーム)。
 */

.equ STACK, 0x00FFFD00

.equ BIOS_CLEAR_VRAM,            0x000002A0
.equ BIOS_LOAD_DEFAULT_VDP_REGS, 0x000002AC
.equ BIOS_VDP_DISP_ENABLE,       0x000002D8
.equ BIOS_CLEAR_COMM,            0x00000340

.equ VDP_DATA, 0x00C00000
.equ VDP_CTRL, 0x00C00004
.equ VDP_HV,   0x00C00008

.equ GA_COMCMD0, 0x00A12010
.equ GA_COMCMD1, 0x00A12012
.equ GA_COMSTAT0, 0x00A12020
.equ GA_COMSTAT1, 0x00A12022
.equ GA_COMSTAT2, 0x00A12024
.equ GA_STOPWATCH, 0x00A1200C		/* 12-bit, 30.72 us/tick, Main read-only */

.equ PROBE_BANK, 0x00200000
.equ O_NRUN_OFF, 0x0000
.equ O_LOADS_OFF, 0x0004

.equ CMD_STREAM, 0x50
.equ CMD_SWAP,   0x51
.equ STAT_BOOT_STAGE, 0x8001		/* sidecar/Dic staging bank is available */
.equ STAT_READY, 0x8003
.equ STAT_END,   0x8004			/* SPからの映画終端通知(15秒待って再ループ) */

.equ NT0, 0xC000
.equ NT1, 0xE000

/* 0xFF2100..0xFF66FF is no longer a tile staging buffer: streamed pattern DMA
   reads Word RAM directly and repairs the first destination word on the CPU.
   Keep this range for boot-time Main-CPU code generation. O_LOADS v2 also
   removes the former 0xFF8800 run table; that interval is unallocated. The
   complete fixed Main-RAM map is:
     M-CODE   0xFF0000..0xFF66FF  resident IP + generated handlers/blitters
     M-STATE  0xFF6700..0xFF87FF  runtime .bss (8.25 KiB worst-case reserve)
     free      0xFF8800..0xFFB1FF
     M-PALTAB 0xFFB200..0xFFB9FF  16 x 128B palette segments
     M-PALIDX 0xFFBA00..0xFFBA3F  16 x 4B palette-switch entries
     M-DIC    0xFFBA40..0xFFFA3F  512-pattern persistent dictionary
     guard    0xFFFA40..0xFFFAFF  cushion below the stack
     M-STACK  0xFFFB00..0xFFFCFF  / M-TOP 0xFFFD00.. BIOS reserve */
.equ MAIN_CODEGEN_BASE,  0x00FF2100
.equ MAIN_CODEGEN_LIMIT, 0x00FF6700	/* M-STATE base = end of M-CODE */
.equ DIC_BUF,            0x00FFBA40	/* persistent dictionary; direct Main-RAM VDP DMA */
.equ DIC_BUF_END,        0x00FFFA40
.equ DIC_BUF_PATTERNS,   512
.equ MAIN_CODEGEN_TABLE_BYTES, 0x0200	/* 256 signed word offsets */
.equ MAIN_CODEGEN_HANDLER_MAX, 70	/* mask FF: guarded before writing */
.equ MAIN_CODEGEN_EXPECTED_END, 0x00FF4A00
.equ MAIN_CODEGEN_BLITTER_MAX, 7296	/* H40 40x28, NT0+NT1 */
.equ DIC_STAGE_OFF,      0x6000		/* copied before frame-0 output reuses this area */

/* Exact 68000 words emitted by init_main_codegen.  Keep synchronized with
   harness/main_codegen/verify_handlers.py. */
.equ CG_OP_MOVE_ENTRY_D3,      0x3618	/* move.w (a0)+,d3 */
.equ CG_OP_STRIP_COLD_D6_D3,   0xC646	/* and.w d6,d3 */
.equ CG_ENTRY_MASK_LONG,       0x67FF67FF
.equ CG_OP_STORE_D3_A1,        0x3283	/* move.w d3,(a1) */
.equ CG_OP_STORE_D3_D16_A1,    0x3343	/* move.w d3,disp(a1) */
.equ CG_OP_ADVANCE_SHADOW,     0x43E9	/* lea 16(a1),a1 */
.equ CG_SHADOW_BYTE_ADVANCE,   16
.equ CG_OP_BRA_W,              0x6000
.equ CG_OP_LEA_SHADOW_A1,      0x43F9	/* lea shadow.l,a1 */
.equ CG_OP_MOVE_L_IMM_ABS,     0x23FC	/* move.l #cmd,(VDP_CTRL).l */
.equ CG_OP_MOVE_L_A1_ABS,      0x23D9	/* move.l (a1)+,(VDP_DATA).l */
.equ CG_OP_MOVE_W_A1_ABS,      0x33D9	/* move.w (a1)+,(VDP_DATA).l */
.equ CG_OP_RTS,                0x4E75
/* DEBUG HUD: only hexadecimal glyphs.  Fixed at VRAM 0xD000 (tiles 1664..1679)
   in the otherwise-unused 0xD000-0xDFFF gap between NT0 and NT1.  Same location
   in DEBUG and release, generic and specialized builds, so the resident pool is
   free to grow right up to NT0 (0xC000) without a font reservation. */
.equ DBGFONT_N, 16
.equ HUD_FONT_ADDR, 0xD000
.equ HUD_FONT_VTILE, HUD_FONT_ADDR/32	/* = 1664; name-table tile index (11-bit, fits) */
/* リリースビルドが既定。make movieplay DEBUG=1 でオーバーレイ一式を有効化
   (画面表示専用。ストリームにDEBUG専用データは持たない) */
/* CRAM pre-load: 全区間パレット表(paltab.bin)と切替表(palidx.bin)はpackが書く
   ビルド入力で、このIPイメージの一時.startup領域に内蔵する。ip_entry冒頭で
   M-PALTAB/M-PALIDXへコピーし、以後codegenが.startupを上書きしても安全。
   区間切替は内蔵PALIDX表(切替frame番号+区間番号)が起点で、ストリーム到着に
   依存しない。容量はav_config.PALTAB_MAX_SEGと一致必須
   (check_player_ring.pyがビルド時検証)。 */
.equ PALTAB_MAX_SEG, 16			/* Main-RAM表の容量(区間数)。16*128B=2KB */
.equ PALTAB_STAGE_BYTES, 0x6000
.equ PALIDX_ENTRIES, 16			/* 15切替 + 0xFFFF frame番兵 */
.equ PALIDX_RAM, 0x00FFBA00		/* M-PALIDX 0xFFBA00..0xFFBA3F */
.equ BOOT_VRAM_DIR_OFF, 0x0FC0
.equ BOOT_VRAM_MAGIC, 0x4256524D		/* "BVRM" */
.equ PALTAB_RAM, 0x00FFB200		/* 表本体 0xFFB200..0xFFBA00 */
/* 1VBLANKで安全に使えるDMA相当word budgetはモード別(md_vbudget)。
   Word-RAM DMAの先頭word補修など、CPUによるVDP word writeはDMAの4倍で
   chargeし、runは残budget境界で次VBLANKへ分ける。 */
.equ VB_WORDS_H32, 2800		/* H32 V28 NTSC */
.equ VB_WORDS_H40, 3200		/* H40 V28 NTSC: setup/CPU work込みの安全側 */
.equ CPU_VDP_WORD_COST, 4	/* one CPU-written VDP word in DMA-word equivalents */
.equ FEATURE_FIXED_N_BIT, 1	/* header features bit 1 */
.equ FEATURE_PATTERN_SUPPLY_BIT, 3
.equ FEATURE_BOOT_VRAM_SIDECAR_BIT, 7
.equ FEATURE_WORDBUF_RING_BIT, 8
.equ SHADOW_UPDATE_LIST_BIT, 15
.equ SHADOW_UPDATE_COUNT_MASK, 0x7FFF
.equ SHADOW_OFFSET_MASK, 0x0FFE	/* 4KB physical shadow, even word offsets */
.equ PACE_VBLANK_TICKS, 543	/* one NTSC VBlank in 30.72us stopwatch ticks */
.equ PACE_ARM_BIAS_TICKS, 286	/* preserves the proven N2 arm point: 2*543-286=800 */

.ifdef DEBUG
.ifdef PLAYER_SPECIALIZED
.equ HUD_HEX_TABLE, 1
.endif
.endif

.ifdef PLAYER_SPECIALIZED
	.include "player_constants.inc"
.equ CTRL_SCR_OFF, PC_CTRL_SCR_OFFSET
.equ STATUS_OFF, PC_STATUS_OFFSET
.equ WR0_OFF, PC_WR0_OFFSET
.equ WR0_END, PC_WR0_END
.equ WR1_OFF, PC_WR1_OFFSET
.equ WR1_END, PC_WR1_END
.equ PACE_FIXED_ARM_TICKS, PC_VSYNC_N*PACE_VBLANK_TICKS-PACE_ARM_BIAS_TICKS
.else
.equ CTRL_SCR_OFF, 0x10000
.equ STATUS_OFF, 0x0AF00
.equ WR0_OFF, 0x15200
.equ WR0_END, 0x1C000
.equ WR1_OFF, 0x15200
.equ WR1_END, 0x1C000
.endif

.ifdef HUD_HEX_TABLE
/* Specialized H32/H40 DEBUG builds publish the same 43 hexadecimal cells.
   Small counters use one digit, Main VBlank spill is packed into the high
   nibble of the 12-bit transfer stopwatch, and reader lead/slot use one
   nibble each. H32 wraps after 32 cells; H40 wraps after 40 cells. */
.equ HUD_FLIP_FIELDS, 1
.equ HUD_SUB_POLL_GAP, 1
.equ HUD_COMBINED_WORDS, 43
.endif

.ifdef PLAYER_SPECIALIZED
.if (PC_FEATURES & 0x0002) != 0
.if PC_MODE == 1
/* Fixed-N specialized H40 builds copy the back name table with one linear
   Main-RAM DMA inside the flip VBlank (64-entry-pitch staging, ~18 blank
   lines) instead of the FIFO-throttled CPU blit (~8 ms of active display).
   The complete 40x28 visible aperture is staged so a smaller encoded grid
   stays centered with zero entries around it.  This frees the pre-transfer
   phase so Pass2 can catch field 1's VBlank. */
.equ NT_DMA_FLIP, 1
.equ NT_STAGE_PITCH, 64
.equ NT_STAGE_ROWS, 28
.equ NT_STAGE_WORDS, NT_STAGE_PITCH*NT_STAGE_ROWS
.equ NT_STAGE_ROW_SKIP, (NT_STAGE_PITCH-PC_TCOLS)*2
/* A shared deadline VBlank must retain enough of the conservative word budget for
   the complete 64-pitch NT DMA, the optional DEBUG HUD staging copy, CRAM on a
   palette switch, and non-payload control/setup time. The staged HUD is
   included in that one NT DMA; DEBUG keeps a conservative word-equivalent
   allowance for its Main-RAM stamp. CPU-written CRAM words use the same 4x
   charge as CPU-written pattern words. */
.ifdef DEBUG
.equ NT_FLIP_HUD_WORDS, HUD_COMBINED_WORDS
.else
.equ NT_FLIP_HUD_WORDS, 0
.endif
.equ NT_FLIP_GUARD_WORDS, 128
.equ NT_FLIP_RESERVE_WORDS, NT_STAGE_WORDS+NT_FLIP_HUD_WORDS+NT_FLIP_GUARD_WORDS
.equ NT_CRAM_FLIP_RESERVE_WORDS, NT_FLIP_RESERVE_WORDS+(64*CPU_VDP_WORD_COST)
.endif
.endif
.endif

.macro PC_MOVE_W runtime, constant, dest
.ifdef PLAYER_SPECIALIZED
	move.w	#\constant, \dest
.else
	move.w	\runtime, \dest
.endif
.endm

.macro PC_MOVE_L runtime, constant, dest
.ifdef PLAYER_SPECIALIZED
	move.l	#\constant, \dest
.else
	move.l	\runtime, \dest
.endif
.endm

.macro PC_CMP_W runtime, constant, dest
.ifdef PLAYER_SPECIALIZED
	cmpi.w	#\constant, \dest
.else
	cmp.w	\runtime, \dest
.endif
.endm

.macro PC_ADD_W runtime, constant, dest
.ifdef PLAYER_SPECIALIZED
	addi.w	#\constant, \dest
.else
	add.w	\runtime, \dest
.endif
.endm

.macro PC_ADDA_W runtime, constant, dest
.ifdef PLAYER_SPECIALIZED
	adda.w	#\constant, \dest
.else
	adda.w	\runtime, \dest
.endif
.endm

/* The specialized DEBUG player knows the HUD font tile base at assembly time.
   Map one byte directly to its two name-table words, avoiding two nibble
   conversions and all formatter calls in the per-frame deadline. */
.macro DBG_PUT2
.ifdef HUD_HEX_TABLE
	andi.w	#0x00FF, d4
	add.w	d4, d4			/* *4: two ADDs beat LSL.W #2 by 2 clocks */
	add.w	d4, d4
	move.l	(a1,d4.w), (a0)+
.else
	bsr	dbg_put2
.endif
.endm

.macro DBG_PUT1
.ifdef HUD_HEX_TABLE
	andi.w	#0x000F, d4
	addi.w	#HUD_FONT_VTILE, d4
	move.w	d4, (a0)+
.else
	bsr	dbg_put1
.endif
.endm

.macro DBG_PUT3
.ifdef HUD_HEX_TABLE
	bsr	dbg_fast_put3
.else
	bsr	dbg_put3
.endif
.endm

.macro DBG_PUT4
.ifdef HUD_HEX_TABLE
	move.w	d4, d3
	lsr.w	#8, d4
	DBG_PUT2
	move.w	d3, d4
	DBG_PUT2
.else
	bsr	dbg_put4
.endif
.endm

.text

	.incbin "security.bin"

	bra.w	ip_entry
	.org	0x584

.global ip_entry
ip_entry:
	move.w	#0x2700, sr
	lea	STACK, sp

	/* IPイメージ内蔵のパレット表(可変長 n_seg*128B)と切替表(64B)をM-RAMへ。
	   格納元は一時.startup領域で、後段のcodegenが上書きするため最初に写す。
	   以後の参照(初期CRAM・区間切替・ループ復帰)はすべてM-PALTAB/M-PALIDX。 */
	lea	paltab_image, a0
	lea	PALTAB_RAM, a1
	move.w	#(paltab_image_end-paltab_image)/2-1, d0
1:
	move.w	(a0)+, (a1)+
	dbra	d0, 1b
	lea	palidx_image, a0
	lea	PALIDX_RAM, a1
	moveq	#PALIDX_ENTRIES-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b
	move.l	#PALIDX_RAM, palidx_ptr

	jsr	BIOS_LOAD_DEFAULT_VDP_REGS
	jsr	BIOS_CLEAR_VRAM
	jsr	BIOS_CLEAR_COMM

	/* VDP: H32, autoinc=2, plane 64x32, VSRAM=0, HScroll/Sprite を安全域へ */
	move.w	#0x8C00, (VDP_CTRL).l		/* reg12 H32 */
	move.w	#0x9001, (VDP_CTRL).l		/* reg16 plane 64x32 */
	move.w	#0x8F02, (VDP_CTRL).l		/* reg15 autoinc 2 */
	move.w	#0x8B00, (VDP_CTRL).l		/* reg11 scroll full-screen */
	move.w	#0x8407, (VDP_CTRL).l		/* reg4  Plane B NT = NT1(0xE000) */
	move.w	#0x8578, (VDP_CTRL).l		/* reg5  sprite table 0xF000 */
	move.w	#0x8D3F, (VDP_CTRL).l		/* reg13 hscroll 0xFC00 */
	move.w	#0x8238, (VDP_CTRL).l		/* reg2  表示=NT1(front)。裏はNT0から構築 */
	move.l	#0x40000010, (VDP_CTRL).l	/* VSRAM=0 */
	move.w	#0, (VDP_DATA).l
	move.w	#0, (VDP_DATA).l

.ifdef PLAYER_SPECIALIZED
.if PC_MODE == 1
	move.w	#0x8C81, (VDP_CTRL).l		/* show the preload counter in H40 too */
.endif
	bsr	draw_startup
.else
	bsr	load_movie_palette
.endif

	jsr	BIOS_VDP_DISP_ENABLE
	move.w	#0x8174, (VDP_CTRL).l		/* reg1: 表示on+vint+DMA許可(M1)+mode5 */

	clr.w	dbg_seg

.ifdef NT_DMA_FLIP
	/* Main RAM .bss is not initialized by the BIOS.  Clear every staged name
	   entry once so columns/rows outside a centered movie remain transparent. */
	lea	nt_stage, a0
	moveq	#0, d0
	move.w	#(NT_STAGE_WORDS/2)-1, d1
1:
	move.l	d0, (a0)+
	dbra	d1, 1b
.endif

	clr.w	back_idx			/* 裏=NT0(0) から構築, 表示=NT1 */

	move.w	#CMD_STREAM, d0
.ifdef PLAYER_SPECIALIZED
	bsr	cmd_wait_startup
	/* Sub has armed BODY and handed over frame 0 with the timed suffix stopped.
	   Keep CMD_STREAM asserted until Main has built and flipped frame 0. */
.else
	bsr	cmd_wait_ready
.endif

	/* frame0準備完了=バンクにヘッダ写し(O_HDR)がある。mode/tcols/trows/pool/base を読み
	   モード依存のVDP設定と実行時変数を確定する(汎用化: H32/H40, mode4は将来) */
	lea	(PROBE_BANK+STATUS_OFF+0x80), a0
.ifndef PLAYER_SPECIALIZED
	move.w	8(a0), md_tcols
	move.w	10(a0), md_trows
	move.w	12(a0), d0			/* cells; supported grids are multiples of 8 */
	lsr.w	#3, d0
	move.w	d0, md_bmbytes
	/* HUD font is fixed at 0xD000 (HUD_FONT_ADDR/HUD_FONT_VTILE); no runtime
	   base+pool computation needed. */
	moveq	#0, d0
	move.b	38(a0), d0			/* mode: 0=H32 1=H40 (2=mode4将来) */
	move.w	d0, md_mode
	/* v4: N(1コマの表示VBLANK数)@52。0(v2/v3ディスク)なら4(=15fps)。表示をN vblank間隔に */
	move.w	52(a0), d0
	bne	1f
	moveq	#4, d0
1:
	/* Feature bit 1 makes the header's N authoritative. Feature-clear N=2
	   remains only a hint, so 24fps keeps its delivery-paced 2/3-VBlank loop. */
	clr.w	md_fixed_n
	btst	#FEATURE_FIXED_N_BIT, 63(a0)
	beq	1f
	move.w	#1, md_fixed_n
1:
	move.w	d0, md_vsync_n
	mulu.w	#PACE_VBLANK_TICKS, d0
	subi.w	#PACE_ARM_BIAS_TICKS, d0
	move.w	d0, md_pace_arm_ticks
	/* Select the VDP width from the stream's mode byte, not from N.
	   N is the frame pacing interval (2 at 30fps, 4 at 15fps), so testing
	   it here made every v4 stream fall through to H40. */
	move.w	#0x8C00, (VDP_CTRL).l		/* reg12 H32 */
	move.w	#32, d2				/* screen_cols */
	move.w	#VB_WORDS_H32, d3
	cmpi.w	#1, md_mode
	bne	1f					/* mode 0=H32; mode 2 is reserved */
	move.w	#0x8C81, (VDP_CTRL).l		/* reg12 H40 */
	move.w	#40, d2
	move.w	#VB_WORDS_H40, d3
1:
.else
.if PC_MODE == 0
	move.w	#0x8C00, (VDP_CTRL).l		/* generated H32 profile */
.elseif PC_MODE == 1
	move.w	#0x8C81, (VDP_CTRL).l		/* generated H40 profile */
.else
	.error "unsupported generated player mode"
.endif
.endif
	/* DEBUG HUD is embedded into the inactive Plane A table after its full movie
	   blit. Disable the Window region explicitly: a Window's transparent pixels
	   expose Plane B, not Plane A, and previously showed stale/wrong-parity data. */
.ifdef DEBUG
	move.w	#0x9100, (VDP_CTRL).l		/* reg17: left of column-pair 0 = no side strip */
	move.w	#0x9200, (VDP_CTRL).l		/* reg18: rows above 0 = no top strip */
.endif
.ifndef PLAYER_SPECIALIZED
	move.w	d3, md_vbudget
	sub.w	md_tcols, d2			/* col0 = (screen_cols-tcols)/2 */
	lsr.w	#1, d2
	move.w	d2, md_col0
	move.w	#28, d2				/* screen_rows(H32/H40) */
	sub.w	md_trows, d2			/* row0 = (screen_rows-trows)/2 */
	lsr.w	#1, d2
	move.w	d2, md_row0
	/* Generic DEBUG builds need the same fps-scaled normal PrgBuf ceiling as
	   generated players: (422-6-ceil(600/fps)) KiB, then KiB -> patterns. */
	moveq	#0, d2
	move.w	56(a0), d2			/* integer content fps */
	bne.s	1f
	moveq	#1, d2				/* corrupt-header divide-by-zero guard */
1:
	move.l	#600, d3
	divu.w	d2, d3
	swap	d3				/* remainder */
	tst.w	d3
	beq.s	2f
	swap	d3
	addq.w	#1, d3				/* ceil(600/fps) */
	bra.s	3f
2:
	swap	d3				/* exact quotient */
3:
	move.w	#414, d2
	sub.w	d3, d2
	lsl.w	#5, d2				/* 1 KiB = 32 patterns */
	move.w	d2, md_prg_buf_cap_patterns
.endif
.ifdef MAIN_CODEGEN
	/* Generate once, before playback. A failed range/size proof leaves
	   md_codegen=0 and the per-bit reference path remains active. */
	bsr	init_main_codegen
.endif
	/* Generic DEBUG builds have no preload counter, so upload the shared font
	   here. Specialized DEBUG/release builds already uploaded it at startup. */
.ifdef DEBUG
.ifndef PLAYER_SPECIALIZED
	move.l	#HUD_FONT_ADDR, d0
	bsr	set_vram_write
	lea	dbgfont, a0
	move.w	#DBGFONT_N*16-1, d1
1:
	move.w	(a0)+, d0			/* each nibble is 0 or 1 */
	move.w	d0, d2
	lsl.w	#1, d2
	or.w	d2, d0
	lsl.w	#1, d2
	or.w	d2, d0
	lsl.w	#1, d2
	or.w	d2, d0			/* 1 -> 0xF independently in every nibble */
	ori.w	#0x1111, d0			/* 0 -> 0x1; 0xF remains 0xF */
	move.w	d0, (VDP_DATA).l
	dbra	d1, 1b
.endif
.endif
	/* Frame -1 is a player-only black state. DEBUG publishes frame=FFFF on it,
	   so capture OCR can find the exact frame=0000 playback boundary. */
	bsr	show_frame_minus_one
	clr.w	frame_no
	clr.w	started
	clr.w	vsync_acc			/* v4: ペーシングカウンタ初期化(.bssはMD上でクリアされない) */
	move.l	#PALIDX_RAM, palidx_ptr		/* ip_entry冒頭でも設定済み(防御的) */
	bsr	prime_fixed_cadence		/* frame0 has no preceding movie flip */
.ifdef DEBUG
	clr.w	sub_wait_lines
	clr.w	dma_elapsed_ticks
	clr.w	dma_start_tick
.ifdef HUD_FLIP_FIELDS
	clr.w	flip_hv_v
	clr.w	pattern_vblank1_exit_v
	clr.w	pass2_entry_q
	clr.w	pattern_dma_ready_v
	clr.w	nt_dma_ready_v
.endif
.endif
play_loop:
	/* Feature bit 1 pairs the Main fixed-N flip deadline with the Sub's exact
	   fixed-N CD rate. Feature-clear 24fps remains delivery paced. */
	tst.w	started
	beq	1f
	bsr	swap_or_end			/* CMD_SWAP → READY(継続) or END(映画終端) */
	cmp.w	#STAT_END, d0
	beq	movie_end_md
1:
	move.w	#1, started
	bsr	build_frame
	tst.w	frame_no			/* one CMD_STREAM edge starts video time + PCM */
	bne.s	1f
	bsr	start_playback
1:

	addq.w	#1, frame_no
	bra	play_loop

/* 映画終端: 最終フレームを表示したまま15秒(900vblank)待ち、先頭からループ再生 */
movie_end_md:
	move.w	#900-1, d2
1:
	bsr	wait_vblank
	dbra	d2, 1b
	move.w	#CMD_STREAM, d0			/* SPを再ストリーム開始させる */
	bsr	cmd_wait_ready			/* BODY arm + frame0 handoff完了まで待つ */
	bsr	show_frame_minus_one
	/* ループ再生: CRAMを区間0へ復帰(最終区間のパレットのままframe0を
	   表示しない)。frame -1は黒画面なので新VBLANK頭で総入替すれば安全。 */
	bsr	wait_vb_start
	bsr	load_movie_palette
	clr.w	frame_no
	clr.w	started
	clr.w	dbg_seg
	move.l	#PALIDX_RAM, palidx_ptr		/* ループ再生: 切替表を先頭へ巻き戻す */
	bsr	prime_fixed_cadence		/* 15s tail already satisfies frame0 cadence */
	bra	play_loop

.ifdef MAIN_CODEGEN
/* Emit the 256 straight-line bitmap handlers once into Main RAM.
   The table stores signed word offsets from MAIN_CODEGEN_BASE.  Every handler
   reads only its set-bit entries, strips the cold flag, writes fixed shadow
   displacements, advances a1 by one bitmap byte, and BRA.Ws to bf_cg_unext.
   Nothing patches or rewrites this region after this routine returns. */
init_main_codegen:
	movem.l	d0-d7/a0-a2, -(sp)
	clr.w	md_codegen
	clr.w	md_codegen_blit
	clr.l	md_codegen_end
	clr.l	md_codegen_blit_addr
	clr.l	md_codegen_blit_addr+4
	lea	MAIN_CODEGEN_BASE, a1		/* jump table cursor */
	lea	(MAIN_CODEGEN_BASE+MAIN_CODEGEN_TABLE_BYTES), a0 /* emitted code cursor */
	moveq	#0, d7				/* mask 0..255 */
1:
	/* Refuse before writing this handler if even the largest template could
	   cross the fixed M-CODE boundary. Partial generated data is harmless
	   while the success flag remains clear. */
	move.l	a0, d0
	addi.l	#MAIN_CODEGEN_HANDLER_MAX, d0
	cmpi.l	#MAIN_CODEGEN_LIMIT, d0
	bhi	9f
	move.l	a0, d0
	subi.l	#MAIN_CODEGEN_BASE, d0
	cmpi.l	#0x7FFF, d0			/* dispatch sign-extends d4.w */
	bhi	9f
	move.w	d0, (a1)+

	moveq	#0, d5				/* source/shadow bit 0..7 */
2:
	btst	d5, d7
	beq	4f
	move.w	#CG_OP_MOVE_ENTRY_D3, (a0)+
	move.w	#CG_OP_STRIP_COLD_D6_D3, (a0)+
	tst.w	d5
	bne	3f
	move.w	#CG_OP_STORE_D3_A1, (a0)+
	bra	4f
3:
	move.w	#CG_OP_STORE_D3_D16_A1, (a0)+
	move.w	d5, d0
	add.w	d0, d0
	move.w	d0, (a0)+
4:
	addq.w	#1, d5
	cmpi.w	#8, d5
	blo	2b

	move.w	#CG_OP_ADVANCE_SHADOW, (a0)+
	move.w	#CG_SHADOW_BYTE_ADVANCE, (a0)+
	move.w	#CG_OP_BRA_W, (a0)+
	/* BRA.W displacement is relative to the PC after its extension word.
	   a0 currently points at that extension word. */
	move.l	#bf_cg_unext, d0
	sub.l	a0, d0
	subq.l	#2, d0
	cmpi.l	#-32768, d0
	blt	9f
	cmpi.l	#32767, d0
	bgt	9f
	move.w	d0, (a0)+

	addq.w	#1, d7
	cmpi.w	#256, d7
	blo	1b

	move.l	a0, d0
	cmpi.l	#MAIN_CODEGEN_EXPECTED_END, d0
	bne	9f
	cmpi.l	#MAIN_CODEGEN_LIMIT, d0
	bhi	9f
	move.l	d0, md_codegen_end
	move.w	#1, md_codegen

	/* Phase 2 needs a valid H32/H40 aperture.  Reject before emitting so the
	   existing generic blitter remains an untouched fallback. */
	PC_MOVE_W md_mode, PC_MODE, d0
	cmpi.w	#1, d0
	bhi	10f
	move.w	#32, d1
	tst.w	d0
	beq	11f
	move.w	#40, d1
11:
	PC_MOVE_W md_tcols, PC_TCOLS, d0
	beq	10f
	cmp.w	d1, d0
	bhi	10f
	PC_MOVE_W md_col0, PC_COL0, d2
	add.w	d0, d2
	cmp.w	d1, d2
	bhi	10f
	PC_MOVE_W md_trows, PC_TROWS, d0
	beq	10f
	cmpi.w	#28, d0
	bhi	10f
	PC_MOVE_W md_row0, PC_ROW0, d2
	add.w	d0, d2
	cmpi.w	#28, d2
	bhi	10f
	move.l	a0, d0
	addi.l	#MAIN_CODEGEN_BLITTER_MAX, d0
	cmpi.l	#MAIN_CODEGEN_LIMIT, d0
	bhi	10f

	move.l	a0, md_codegen_blit_addr
	move.l	#NT0, d6
	bsr	emit_main_blitter
	move.l	a0, md_codegen_blit_addr+4
	move.l	#NT1, d6
	bsr	emit_main_blitter
	move.l	a0, d0
	cmpi.l	#MAIN_CODEGEN_LIMIT, d0
	bhi	10f				/* preflight above makes this defensive only */
	move.l	d0, md_codegen_end
	move.w	#1, md_codegen_blit
	bra	10f
9:
	move.l	a0, md_codegen_end		/* diagnostic only; fallback stays selected */
10:
	movem.l	(sp)+, d0-d7/a0-a2
	rts

/* Emit one fixed-geometry name-table blitter at a0. d6 is NT0 or NT1; the
   caller has already proved the H40 maximum pair fits below M-CODE's end. */
emit_main_blitter:
	move.w	#CG_OP_LEA_SHADOW_A1, (a0)+
	move.l	#shadow, (a0)+
	PC_MOVE_W md_row0, PC_ROW0, d4
	PC_MOVE_W md_trows, PC_TROWS, d5
	subq.w	#1, d5
1:
	/* Precompute the exact command produced by set_vram_write for this row. */
	moveq	#0, d0
	move.w	d4, d0
	lsl.w	#7, d0				/* plane row * 128 bytes */
	PC_MOVE_W md_col0, PC_COL0, d1
	add.w	d1, d1				/* centered column * 2 bytes */
	add.w	d1, d0
	add.l	d6, d0				/* NT0/NT1 base */
	move.l	d0, d1
	andi.l	#0x3FFF, d0
	swap	d0
	ori.l	#0x40000000, d0
	lsr.w	#7, d1
	lsr.w	#7, d1
	andi.w	#3, d1
	or.w	d1, d0
	move.w	#CG_OP_MOVE_L_IMM_ABS, (a0)+
	move.l	d0, (a0)+
	move.l	#VDP_CTRL, (a0)+

	PC_MOVE_W md_tcols, PC_TCOLS, d2
	lsr.w	#1, d2				/* two name-table words per MOVE.L */
	beq	3f
	subq.w	#1, d2
2:
	move.w	#CG_OP_MOVE_L_A1_ABS, (a0)+
	move.l	#VDP_DATA, (a0)+
	dbra	d2, 2b
3:
	PC_MOVE_W md_tcols, PC_TCOLS, d2
	andi.w	#1, d2
	beq	4f
	move.w	#CG_OP_MOVE_W_A1_ABS, (a0)+
	move.l	#VDP_DATA, (a0)+
4:
	addq.w	#1, d4
	dbra	d5, 1b
	move.w	#CG_OP_RTS, (a0)+
	rts
.endif

/* Build and flip one frame. The Sub has already expanded every physical run
   into a VDP-ready 22-byte O_LOADS v2 record, so Main performs no staging pass.
   The same Word-RAM cursor first drives name updates, then the VBlank DMA pass. */
build_frame:
	movem.l	d0-d7/a0-a3, -(sp)
.ifdef DEBUG
	clr.w	vsync_acc			/* per-frame VBlank-start waits shown as Mxx */
	clr.w	frame_vblank_waits
	clr.w	dma_elapsed_ticks		/* H40 Uxxxx: Main pattern-transfer stopwatch ticks */
.endif
	move.w	(PROBE_BANK+O_NRUN_OFF).l, n_runs
bf_upd:
	/* Read bitmap+entries directly from the linear control block in the swapped
	   Word-RAM bank.  The Sub already walks them to build cold runs; rewriting
	   every (cell,entry) pair was duplicate work on the bottleneck CPU. */
	lea	(PROBE_BANK+CTRL_SCR_OFF+4), a0	/* skip total_len + frame_seq */
	move.w	(a0)+, d7			/* bit15=list format, low15=n_upd */
	move.w	d7, d6			/* preserve format tag */
	andi.w	#SHADOW_UPDATE_COUNT_MASK, d7
	beq	bf_blit
	btst	#SHADOW_UPDATE_LIST_BIT, d6
	bne	bf_update_list
	movea.l	a0, a2				/* bitmap */
	PC_ADDA_W md_bmbytes, PC_BMBYTES, a0	/* entries */
.ifdef PLAYER_SPECIALIZED
.if (PC_BMBYTES & 1)
	addq.l	#1, a0				/* v20 retains the aligned 16-bit entry array */
.endif
.else
	move.w	md_bmbytes, d0
	btst	#0, d0
	beq.s	1f
	addq.l	#1, a0
1:
.endif
	lea	shadow, a1
	PC_MOVE_W md_bmbytes, PC_BMBYTES, d5
	subq.w	#1, d5
.ifdef MAIN_CODEGEN
	/* The fixed flag check is the only generated success-path overhead.  The
	   fallback branches around the generated loop; the successful loop falls
	   directly into bf_blit. */
	move.w	(md_codegen).l, d0
	bne	bf_cg_start
.endif
bf_ubyte:
	move.b	(a2)+, d0
	beq	bf_uzero			/* no entries: advance eight shadow words at once */
	cmpi.b	#0xFF, d0
	beq	bf_ufull			/* all entries: straight pointer writes, no bit branches */
	moveq	#7, d4
bf_ubit:
	lsr.b	#1, d0
	bcc	1f
	move.w	(a0)+, d3
	andi.w	#0x67FF, d3			/* strip cold and Prg/Wr/Dic source bits */
	move.w	d3, (a1)
1:
	addq.l	#2, a1
	dbra	d4, bf_ubit
	bra	bf_unext
bf_uzero:
	lea	16(a1), a1
	bra	bf_unext
bf_ufull:
	.rept 8
	move.w	(a0)+, d3
	andi.w	#0x67FF, d3
	move.w	d3, (a1)+
	.endr
bf_unext:
	dbra	d5, bf_ubyte
.ifdef MAIN_CODEGEN
	bra	bf_blit				/* failed generator: safe reference fallback */
bf_cg_uzero:
	lea	16(a1), a1
	bra	bf_cg_unext
bf_cg_ufull:
	.rept 4
	move.l	(a0)+, d3
	and.l	d6, d3				/* strip two packed cold flags */
	move.l	d3, (a1)+
	.endr
	bra	bf_cg_unext
bf_cg_start:
	lea	MAIN_CODEGEN_BASE, a3
	move.l	#CG_ENTRY_MASK_LONG, d6		/* shared word/long cold-flag mask */
bf_cg_ubyte:
	move.b	(a2)+, d0
	beq	bf_cg_uzero			/* exactly the reference zero-mask path */
	cmpi.b	#0xFF, d0
	beq	bf_cg_ufull
	andi.w	#0x00FF, d0			/* MOVE.B leaves the upper byte unchanged */
	add.w	d0, d0				/* signed-word table index */
	move.w	(a3,d0.w), d4
	jmp	(a3,d4.w)				/* prefetch starts generated handler */
bf_cg_unext:
	dbra	d5, bf_cg_ubyte
.endif
bf_blit:
	/* シャドウ全体を裏NTへ blit (裏は非表示=active可) */
	moveq	#0, d5
	move.w	back_idx, d5
	lsl.l	#8, d5
	lsl.l	#5, d5				/* back_idx*0x2000 */
	add.l	#NT0, d5			/* back_base = 0xC000 or 0xE000 (flipまで保持) */
.ifdef NT_DMA_FLIP
	/* Re-stage only the encoded grid at its centered location inside the
	   zeroed 64-entry-pitch visible aperture.  The flip-blank copy remains
	   ONE linear DMA. */
	lea	shadow, a0
	lea	nt_stage+((PC_ROW0*NT_STAGE_PITCH+PC_COL0)*2), a1
	move.w	#PC_TROWS-1, d0
9:
	.rept PC_TCOLS/2
	move.l	(a0)+, (a1)+
	.endr
.if (PC_TCOLS & 1) != 0
	move.w	(a0)+, (a1)+
.endif
	lea	NT_STAGE_ROW_SKIP(a1), a1
	dbra	d0, 9b
	bra	bf_dma				/* NT copied by DMA inside the flip blank */
.endif
.ifdef MAIN_CODEGEN
	move.w	(md_codegen_blit).l, d0
	beq	bf_blit_reference
	move.w	(back_idx).l, d0
	lsl.w	#2, d0
	lea	(md_codegen_blit_addr).l, a3
	movea.l	(a3,d0.w), a3
	jsr	(a3)
	bra	bf_dma
bf_blit_reference:
.endif
	lea	shadow, a1
	PC_MOVE_W md_row0, PC_ROW0, d4	/* plane_row = (screen_rows-trows)/2 */
	PC_MOVE_W md_trows, PC_TROWS, d6
	subq.w	#1, d6
bf_row:
	move.w	d4, d1
	lsl.w	#7, d1				/* plane_row*128 */
.ifdef PLAYER_SPECIALIZED
.if PC_COL0 != 0
	addi.w	#PC_COL0*2, d1			/* generated horizontal centering */
.endif
.else
	add.w	md_col0, d1
	add.w	md_col0, d1			/* +col0*2 (横センタリング) */
.endif
	move.l	d5, d0
	andi.l	#0xFFFF, d1
	add.l	d1, d0				/* NT addr */
	bsr	set_vram_write
	PC_MOVE_W md_tcols, PC_TCOLS, d2
	move.w	d2, d1
	lsr.w	#3, d1
	beq.s	bf_btail
	subq.w	#1, d1
bf_bw:
	move.l	(a1)+, (VDP_DATA).l		/* high word then low word at the VDP data port */
	move.l	(a1)+, (VDP_DATA).l
	move.l	(a1)+, (VDP_DATA).l
	move.l	(a1)+, (VDP_DATA).l
	dbra	d1, bf_bw
bf_btail:
	andi.w	#7, d2				/* preserve arbitrary per-source widths, not just 32/40 */
	beq.s	bf_bdone
	subq.w	#1, d2
bf_bword:
	move.w	(a1)+, (VDP_DATA).l
	dbra	d2, bf_bword
bf_bdone:
	addq.w	#1, d4
	dbra	d6, bf_row

	/* CRAM総入替は flip と同一VBLANKで行う(bf_flip側)。ここで先に書くと、
	   タイルDMAが複数vblankに渡る間「旧フレーム表示×新パレット」が見える
	   (パレット区間切替の瞬間に実機側だけ明るいゴミタイルが出る実バグ)。 */
bf_dma:
	/* Pass2: 表を順に Word-RAM からVRAMへ転送。VBLANK予算(d7)でランをまたいで分割。
	   長runのWord-RAM DMAは先頭1ワードが化ける(実測/Sega文書)ため、src+2/full lengthを
	   dstへDMAした後、チャンク先頭の1ワードをCPUで上書き修復する。短runはCPU直書き。
	   d7はDMA相当cost、DEBUGのa1はHUDへ出すlogical pattern word数。 */
.ifdef HUD_FLIP_FIELDS
	/* E: how late the pre-transfer Main work (swap wait, parse, bitmap, NT
	   blit) reached this point, in 4-tick units since the previous flip.
	   Captured before the blank wait, so it is the deadline-side phase the
	   plain U (transfer interval) cannot show. */
	move.w	(GA_STOPWATCH).l, d0
	sub.w	pace_flip_tick, d0
	andi.w	#0x0FFF, d0
	lsr.w	#2, d0
	cmpi.w	#0xFF, d0
	bls.s	7f
	move.w	#0xFF, d0
7:
	move.w	d0, pass2_entry_q
.endif
	/* Keep this clear before the n_runs load: MOVE supplies the Z flag consumed
	   by the following BEQ. */
.ifdef DEBUG
	moveq	#0, d0
	move.l	d0, pattern_vblank1_words
	move.l	d0, pattern_vblank3_words
	clr.w	pattern_exit_v
	clr.w	pattern_vblank1_exit_v
	clr.w	pattern_dma_ready_v
	clr.w	nt_dma_ready_v
.endif
	clr.w	pattern_transfer_vblanks
.ifdef NT_DMA_FLIP
	clr.w	vbudget_held_reserve
	move.w	#NT_FLIP_RESERVE_WORDS, d0
	movea.l	palidx_ptr, a0
	move.w	frame_no, d1
	cmp.w	(a0), d1
	blo.s	7f
	addi.w	#64*CPU_VDP_WORD_COST, d0
7:
	move.w	d0, pattern_final_reserve_words
.endif
	clr.w	vbudget_from_head		/* no stale budget may authorize a shared flip */
	move.w	n_runs, d4
	beq	bf_flip
	move.w	#1, pattern_transfer_vblanks
	lea	(PROBE_BANK+O_LOADS_OFF), a2
.ifdef DEBUG
	moveq	#0, d0
	movea.l	d0, a1				/* exact logical words in the current budget */
	move.w	(VDP_HV).l, d0
	lsr.w	#8, d0
	move.w	d0, pattern_dma_ready_v		/* ready phase before waiting for a fresh blank head */
.endif
	bsr	bf_start_vbudget		/* full budget only from a proven blank head */
.ifdef DEBUG
	move.w	(GA_STOPWATCH).l, d0
	move.w	d0, dma_start_tick		/* begin inside the first fresh VBlank budget */
.endif
bf_run_lp:
	/* Pop the Sub-built record straight into the control port. Inline Prg
	   payload follows its own record; Wr/Dic records are adjacent. */
	move.w	(a2)+, d1			/* +0 len(語) */
	move.w	d1, d6
	addq.w	#CPU_VDP_WORD_COST, d6		/* full DMA + one CPU repair word */
	cmp.w	d7, d6				/* whole run fits the remaining budget? */
	bls.s	1f
	bra	bf_split_run			/* fill this budget before continuing the run */
1:
	move.w	#0x8F02, (VDP_CTRL).l		/* autoinc=2 (reassert before every DMA) */
	move.w	(a2)+, (VDP_CTRL).l		/* +2 reg93 */
	move.w	(a2)+, (VDP_CTRL).l		/* +4 reg94 */
	move.l	(a2)+, d0			/* +6 cmd */
	addq.l	#2, a2				/* skip +10 dst */
	move.w	(a2)+, (VDP_CTRL).l		/* +12 reg95 */
	move.w	(a2)+, (VDP_CTRL).l		/* +14 reg96 */
	move.w	(a2)+, (VDP_CTRL).l		/* +16 reg97 */
	move.l	d0, d2
	ori.w	#0x0080, d0			/* CD5 in the second control word */
	move.l	d0, (VDP_CTRL).l		/* high word, then CD5 trigger word */
	bsr	wait_dma_done
	move.l	d2, (VDP_CTRL).l		/* restore ordinary destination */
	movea.l	(a2)+, a3			/* +18 src */
	cmpa.l	a2, a3				/* Prg raw source equals the inline payload cursor */
	bne.s	1f
	move.w	d1, d0
	add.w	d0, d0				/* DMA words -> inline bytes */
	adda.w	d0, a2
1:
	move.w	(a3), (VDP_DATA).l		/* repair dst[0] (redundant-correct for DicBuf) */
.ifdef DEBUG
	adda.w	d1, a1
.endif
	sub.w	d6, d7
	bra	bf_run_done

bf_split_run:
	/* Walk the record's raw dst/len/src across one or more budget chunks. */
	move.w	8(a2), d3			/* +10 dst (a2 is at +2) */
	movea.l	16(a2), a3			/* +18 src */
	adda.w	#20, a2				/* advance to the next record */
	cmpa.l	a2, a3
	bne.s	1f
	move.w	d1, d0
	add.w	d0, d0				/* skip this Prg run's inline payload */
	adda.w	d0, a2
1:
bf_chunk:
	tst.w	d7
	ble	bf_chunk_refill
	cmpa.l	#DIC_BUF, a3			/* Word-RAM chunk also needs one CPU repair */
	bcc.s	1f
	cmpi.w	#CPU_VDP_WORD_COST, d7
	bls	bf_chunk_refill
1:
	move.w	d7, d6				/* data words fitting the remaining cost */
	cmpa.l	#DIC_BUF, a3
	bcc.s	2f
	subq.w	#CPU_VDP_WORD_COST, d6
2:
	cmp.w	d1, d6
	bls.s	3f
	move.w	d1, d6
3:
	cmpa.l	#DIC_BUF, a3			/* DicBuf has normal DMA; Prg/Wr sources are Word RAM */
	bcs.s	4f
	bsr	dma_chunk
	sub.w	d6, d7
	bra.s	5f
4:
	bsr	dma_chunk_wr			/* Word-RAM DMA + first-word repair */
	sub.w	d6, d7
	subq.w	#CPU_VDP_WORD_COST, d7
5:
.ifdef DEBUG
	adda.w	d6, a1
.endif
	sub.w	d6, d1				/* ラン残 -= chunk */
	add.w	d6, d6				/* chunk*2 = バイト */
	adda.w	d6, a3				/* src += バイト */
	add.w	d6, d3				/* dst += バイト */
	tst.w	d1
	bne	bf_chunk
	bra	bf_run_done
bf_chunk_refill:
	bsr	bf_next_vbudget
	bra	bf_chunk

bf_run_done:
	subq.w	#1, d4
	bne	bf_run_lp
bf_flip:
.ifdef NT_DMA_FLIP
	/* The cadence-final budget withheld this capacity from patterns. Restore it
	   for the shared NT/HUD/CRAM/flip admission check. */
	move.w	vbudget_held_reserve, d0
	beq.s	8f
	add.w	d0, d7
	clr.w	vbudget_held_reserve
8:
.endif
.ifdef DEBUG
	tst.w	n_runs
	beq.s	1f
	bsr	bf_debug_snapshot_vbudget
	move.w	(VDP_HV).l, d0
	lsr.w	#8, d0
	move.w	d0, pattern_exit_v
	move.w	(GA_STOPWATCH).l, d0
	sub.w	dma_start_tick, d0
	andi.w	#0x0FFF, d0			/* stopwatch wraps naturally after 4096 ticks */
	move.w	d0, dma_elapsed_ticks
1:
	move.w	vsync_acc, frame_vblank_waits	/* exclude display pacing from vblank_spill */
	tst.w	frame_no			/* frame 0 is an untimed boot construction */
	bne.s	1f
	clr.w	frame_vblank_waits		/* its VBlank count is not playback load */
1:
.ifdef NT_DMA_FLIP
	/* A two-VBlank transfer formatted the static HUD after its first budget.
	   One-/zero-VBlank frames still have the whole inter-flip active interval
	   available here. Patch only transfer-final fields on the deadline path. */
	cmpi.w	#2, pattern_transfer_vblanks
	bhs.s	2f
	bsr	prepare_dbg
	bsr	stamp_dbg_stage
2:
.endif
.endif
	/* Precompute the display-register write before the cadence wait.
	   do_flip performs only a final VBlank check followed by this command, so
	   the check-to-reg2 race is a few bus cycles instead of an address/branch
	   calculation at the end of VBlank. */
	move.l	d5, d0
	lsr.l	#8, d0
	lsr.l	#2, d0				/* back_base>>10 */
	andi.w	#0xFF, d0
	ori.w	#0x8200, d0
	move.w	d0, d5				/* prebuilt reg2 word */
	/* パレット区間切替: CRAM総入替(64語≈0.1ms)→flip を新しいvblank頭で連続実行=
	   同一VBLANK内で原子的。DEBUGフォントはP0/index15固定なので切替時作業はない。
	   トリガはplayer内蔵のM-PALIDX表: next_switch <= frame_no の間advance
	   (等値比較にしない=heldフレームで切替frameを跨いでも失われない)。最後に
	   跨いだentryの区間を採用=絶対値の自己修復性を維持。表は15切替+0xFFFF番兵
	   で必ず終端されるためadvanceは有界。CRAM本体はboot時に積んだMain-RAMの
	   PALTAB表から引く(ストリーム到着タイミング非依存)。 */
	movea.l	palidx_ptr, a0
	move.w	frame_no, d1
	cmp.w	(a0), d1
	blo	bf_doflip			/* next_switch > frame_no: 切替なし */
1:
	move.w	2(a0), d0			/* PALTAB区間番号 */
	addq.l	#4, a0
	cmp.w	(a0), d1
	bhs.s	1b				/* 複数跨ぎは最後のentryを採用 */
	move.l	a0, palidx_ptr
	move.w	d0, dbg_seg			/* 絶対値で更新(増分でなく自己修復) */
.ifndef NT_DMA_FLIP
	lsl.w	#7, d0				/* *128B */
	lea	PALTAB_RAM, a0
	adda.w	d0, a0				/* src = 表[区間] (最大15*128=1920でadda.w可) */
.endif
.ifdef DEBUG
.ifndef NT_DMA_FLIP
	bsr	prepare_dbg			/* build the inactive HUD row before the deadline */
	bsr	publish_dbg
.endif
.endif
.ifdef PLAYER_SPECIALIZED
.if (PC_FEATURES & 0x0002) != 0
.ifdef NT_DMA_FLIP
	move.w	#NT_CRAM_FLIP_RESERVE_WORDS, d6
.ifdef DEBUG
	move.w	(VDP_HV).l, d0
	lsr.w	#8, d0
	move.w	d0, nt_dma_ready_v		/* ready phase before the cadence-final VBlank wait */
.endif
	bsr	bf_wait_fixed_flip_vblank	/* share the budgeted deadline blank when safe */
.ifdef DEBUG
	bsr	bf_patch_dbg_stage		/* final fields enter the one NT DMA */
.endif
.else
	bsr	wait_fixed_palette_flip		/* cadence target plus a fresh CRAM VBlank */
.endif
.else
	bsr	wait_vb_start			/* 頭から使える新しいvblank(CRAM+flipが確実に収まる) */
.endif
.else
	tst.w	md_fixed_n
	beq.s	1f
	bsr	wait_fixed_palette_flip		/* cadence target plus a fresh CRAM VBlank */
	bra.s	2f
1:
	bsr	wait_vb_start			/* 頭から使える新しいvblank(CRAM+flipが確実に収まる) */
2:
.endif
.ifdef NT_DMA_FLIP
	bsr	nt_dma_flip			/* whole back NT in ~11 blank lines */
	move.w	dbg_seg, d0
	lsl.w	#7, d0
	lea	PALTAB_RAM, a0
	adda.w	d0, a0				/* recover CRAM source after DEBUG stage patch */
.endif
	move.l	#0xC0000000, (VDP_CTRL).l	/* CRAM addr 0 */
	move.w	#64-1, d1
1:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d1, 1b
	bsr	do_flip				/* CRAM直後・同vblank内にflip */
	bra	bf_after_flip
bf_doflip:
	/* Pattern DMA normally leaves us inside VBlank. The H40 fixed-N path has
	   already formatted its HUD outside the second transfer deadline and folds
	   the final row into nt_stage before the one name-table DMA. Other paths
	   publish the inactive HUD before cadence waiting. Re-check immediately
	   before the atomic flip; count a newly waited VBlank through wait_vb_start
	   just like a split DMA. */
.ifdef DEBUG
.ifndef NT_DMA_FLIP
	bsr	prepare_dbg
	bsr	publish_dbg
.endif
.endif
.ifdef PLAYER_SPECIALIZED
.if (PC_FEATURES & 0x0002) != 0
.ifdef NT_DMA_FLIP
	move.w	#NT_FLIP_RESERVE_WORDS, d6
.ifdef DEBUG
	move.w	(VDP_HV).l, d0
	lsr.w	#8, d0
	move.w	d0, nt_dma_ready_v		/* ready phase before the cadence-final VBlank wait */
.endif
	bsr	bf_wait_fixed_flip_vblank	/* cold tail + NT DMA + flip share the deadline */
.ifdef DEBUG
	bsr	bf_patch_dbg_stage		/* final fields enter the one NT DMA */
.endif
	bsr	nt_dma_flip
.else
	bsr	wait_fixed_flip			/* normal frame: exactly N flip-to-flip VBlanks */
.endif
.endif
.else
	tst.w	md_fixed_n
	beq.s	1f
	bsr	wait_fixed_flip			/* normal frame: exactly N flip-to-flip VBlanks */
1:
.endif
	bsr	do_flip
bf_after_flip:
.ifndef DEBUG
	/* Release build has no Sxx HUD, so retain the existing red slip indicator. */
	move.w	(PROBE_BANK+STATUS_OFF+0x00).l, d0
	beq	1f
	move.l	#0xC0000000, (VDP_CTRL).l
	move.w	#0x000E, (VDP_DATA).l
1:
.endif
	movem.l	(sp)+, d0-d7/a0-a3
	rts

bf_update_list:
	/* Completed (shadow byte offset, final name-table entry) pairs.  Masking
	   every untrusted offset into the expanded 4KB shadow allocation is cheaper
	   and safer than a taken/not-taken range branch per item.  This out-of-line
	   walker keeps the successful generated-bitmap path's fall-through intact. */
	lea	shadow, a1
	subq.w	#1, d7
1:
	move.w	(a0)+, d0
	andi.w	#SHADOW_OFFSET_MASK, d0
	move.w	(a0)+, (a1,d0.w)
	dbra	d7, 1b
	bra	bf_blit

/* Start Pass2 with one honest VBlank word budget.  An already-active display
   waits for the next blank.  An already-entered blank may keep the full budget
   only on its first V-counter line; later entry waits for the following head
   instead of pretending all md_vbudget words remain.  d7 returns the full
   budget and vbudget_from_head records that its time origin is trustworthy.
   Trashes d0. */
bf_start_vbudget:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq	bf_refill_vbudget
	move.w	(VDP_HV).l, d0
	lsr.w	#8, d0
	cmpi.w	#0x00E0, d0
	bne	bf_refill_vbudget
	move.w	#1, vbudget_from_head
	PC_MOVE_W md_vbudget, PC_VBUDGET, d7
	rts

bf_refill_vbudget:
	bsr	wait_vb_start
	move.w	#1, vbudget_from_head
	PC_MOVE_W md_vbudget, PC_VBUDGET, d7
.ifdef NT_DMA_FLIP
	/* Pattern budget N is also the fixed-cadence display deadline. Withhold
	   its final display work before issuing any pattern transfer. */
	clr.w	vbudget_held_reserve
	cmpi.w	#PC_VSYNC_N, pattern_transfer_vblanks
	bne.s	1f
	move.w	pattern_final_reserve_words, d0
	sub.w	d0, d7
	move.w	d0, vbudget_held_reserve
1:
.endif
	rts

.ifdef DEBUG
/* Snapshot exact logical pattern words issued in the current VBlank budget.
   They intentionally differ from d7's DMA-equivalent cost when CPU writes run.
   Four counters cover every fixed cadence supported by av_config. T may still
   exceed four and makes a physically overloaded fifth transfer blank visible.
   Trashes d0/d6/a0. */
bf_debug_snapshot_vbudget:
	move.l	a1, d0
	move.w	pattern_transfer_vblanks, d6
	cmpi.w	#4, d6
	bhi.s	2f
	subq.w	#1, d6
	add.w	d6, d6
	lea	pattern_vblank1_words, a0
	move.w	d0, (a0,d6.w)
	cmpi.w	#1, pattern_transfer_vblanks
	bne.s	2f
	move.w	(VDP_HV).l, d0
	lsr.w	#8, d0
	move.w	d0, pattern_vblank1_exit_v
2:
	rts

/* Finish the current budget snapshot before waiting for the next fresh head. */
bf_next_vbudget:
	bsr	bf_debug_snapshot_vbudget
.ifdef NT_DMA_FLIP
	/* On the first split only, spend the active-display gap before VBlank 2
	   formatting every HUD field that is already known. Transfer-final fields
	   are patched after the last pattern word. */
	cmpi.w	#1, pattern_transfer_vblanks
	bne.s	1f
	bsr	prepare_dbg
	bsr	stamp_dbg_stage
1:
.endif
	suba.l	a1, a1				/* exact logical-word counter for the next budget */
	addq.w	#1, pattern_transfer_vblanks
	bra	bf_refill_vbudget
.else
bf_next_vbudget:
	addq.w	#1, pattern_transfer_vblanks
	bra	bf_refill_vbudget
.endif

.ifdef NT_DMA_FLIP
/* Fixed-N H40 only. d6 is the word reserve for NT/HUD/optional CRAM/guard.
   If Pass2 ended inside a VBlank whose budget began at its head, and the
   residual word budget covers all flip work, keep that exact cadence VBlank.
   Otherwise retain the old fresh-start path.  The target blank is display
   pacing as well as the final pattern chunk, so DEBUG M excludes that shared
   wait and continues to count only intervening pattern-work blanks.
   Trashes d0. */
bf_wait_fixed_flip_vblank:
	bsr	wait_fixed_flip
	tst.w	vbudget_from_head
	beq.s	2f
	cmp.w	d6, d7
	blo.s	2f
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq.s	2f
	move.w	(VDP_HV).l, d0
	cmpi.w	#0xFC00, d0
	bhs.s	2f
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq.s	2f
.ifdef DEBUG
	/* Only remove a wait when pattern work itself occupied the cadence's
	   display-deadline VBlank. If it finished earlier (common at N=4), every
	   counted wait belongs to an earlier opened VBlank budget. */
	move.w	pattern_transfer_vblanks, d0
	cmp.w	#PC_VSYNC_N, d0
	blo.s	1f
	tst.w	frame_vblank_waits
	beq.s	1f
	subq.w	#1, frame_vblank_waits
1:
.endif
	rts
2:
	bsr	wait_vb_start
	rts

.ifdef DEBUG
/* Refresh fields whose final values are not available when a split frame
   preformats and stages its HUD between opened VBlank budgets. Write directly into
   the H40 64-entry-pitch stage consumed by the imminent one NT DMA.
   Trashes d0/d3/d4/a0. */
bf_patch_dbg_stage:
	lea	dbg_hex_pairs, a1
	lea	nt_stage+4*2, a0		/* final palette segment */
	move.w	dbg_seg, d4
	bsr	dbg_put1
	lea	nt_stage+15*2, a0		/* spill nibble + transfer ticks */
	move.w	dma_elapsed_ticks, d4
	andi.w	#0x0FFF, d4
	move.w	frame_vblank_waits, d0
	andi.w	#0x000F, d0
	ror.w	#4, d0
	or.w	d0, d4
	bsr	dbg_stage_put4
	lea	nt_stage+36*2, a0		/* transfer VBlanks/end V-counter */
	move.w	pattern_transfer_vblanks, d4
	bsr	dbg_put1
	move.w	pattern_exit_v, d4
	bsr	dbg_stage_put2
	rts

/* Deadline-side byte pairs use the specialized 256-entry tile-pair table.
   Keep these small out-of-line helpers so every final field is fast without
   duplicating the table lookup at seven call sites. */
dbg_stage_put4:
	move.w	d4, d3
	lsr.w	#8, d4
	bsr	dbg_stage_put2
	move.w	d3, d4
	bra	dbg_stage_put2

dbg_stage_put2:
	andi.w	#0x00FF, d4
	add.w	d4, d4
	add.w	d4, d4
	move.l	(a1,d4.w), (a0)+
	rts
.endif
.endif

/* vblankに入るまで待つ(既に中なら即戻る)。trashes d0 */
wait_vb_in:
1:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq	1b
	rts

/* 次のvblank開始まで待つ(vblank中なら一度activeを抜けてから)。予算補充用。trashes d0 */
wait_vb_start:
1:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	bne	1b				/* active(非vblank)になるまで */
2:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq	2b				/* vblankに入るまで */
	addq.w	#1, vsync_acc			/* v4: 1コマのVBLANK数を計上(表示ペーシング用) */
	rts

/* Make frame 0 immediately eligible: its synthetic preceding flip is one
   fixed-N arm threshold in the past. Trashes d0. */
prime_fixed_cadence:
.ifdef PLAYER_SPECIALIZED
.if (PC_FEATURES & 0x0002) != 0
	move.w	(GA_STOPWATCH).l, d0
	sub.w	#PACE_FIXED_ARM_TICKS, d0
	andi.w	#0x0FFF, d0
	move.w	d0, pace_flip_tick
.endif
.else
	tst.w	md_fixed_n
	beq.s	1f
	move.w	(GA_STOPWATCH).l, d0
	sub.w	md_pace_arm_ticks, d0
	andi.w	#0x0FFF, d0
	move.w	d0, pace_flip_tick
1:
.endif
	rts

/* The stopwatch arm point is safely after VBlank N-1 ends and before VBlank N
   begins. do_flip performs the authoritative VBlank/end guard immediately
   beside the precomputed register write. */
wait_fixed_flip:
1:
	move.w	(GA_STOPWATCH).l, d0
	sub.w	pace_flip_tick, d0
	andi.w	#0x0FFF, d0
	PC_CMP_W md_pace_arm_ticks, PACE_FIXED_ARM_TICKS, d0
	bcc.s	2f
	bra.s	1b
2:
	rts

/* CRAM replacement needs a fresh VBlank. At the arm point the next fresh
   start is exactly the fixed-N target VBlank. */
wait_fixed_palette_flip:
1:
	move.w	(GA_STOPWATCH).l, d0
	sub.w	pace_flip_tick, d0
	andi.w	#0x0FFF, d0
	PC_CMP_W md_pace_arm_ticks, PACE_FIXED_ARM_TICKS, d0
	bcc.s	2f
	bra.s	1b
2:
	bsr	wait_vb_start
	rts

/* Final display flip. d5 is the precomputed reg2 word. Re-check VBlank here,
   immediately next to the control-port write, so an end-of-blank race cannot
   defer an otherwise on-time frame.  trashes d0. */
do_flip:
	/* Accept the target VBlank even when frame work reached it after the midpoint,
	   but never accept its final four V-counter lines.  The NTSC counter is not
	   monotonic across all VBlank lines, yet FC..FF is always the terminal tail.
	   Re-read status after HV so a boundary between the first two reads is also
	   caught.  A guarded/fresh return from wait_vb_start has the full blank. */
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq.s	2f
	move.w	(VDP_HV).l, d0
	cmpi.w	#0xFC00, d0
	bhs.s	2f
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	bne.s	1f
2:
	bsr	wait_vb_start
1:
	move.w	d5, (VDP_CTRL).l
	eori.w	#1, back_idx			/* 裏を反転 */
.ifdef PLAYER_SPECIALIZED
.if (PC_FEATURES & 0x0002) != 0
.ifdef HUD_FLIP_FIELDS
	/* Off the critical path, record the accepted flip V-counter and make this
	   exact flip the next fixed-N cadence origin. */
	move.w	d1, -(sp)
	move.w	(VDP_HV).l, d1
	lsr.w	#8, d1
	move.w	d1, flip_hv_v
	move.w	(GA_STOPWATCH).l, d1
	move.w	d1, pace_flip_tick		/* exact flip-to-flip deadline */
	move.w	(sp)+, d1
.else
	move.w	(GA_STOPWATCH).l, pace_flip_tick	/* exact flip-to-flip deadline */
.endif
.endif
.else
	tst.w	md_fixed_n
	beq.s	1f
	move.w	(GA_STOPWATCH).l, pace_flip_tick	/* exact flip-to-flip deadline */
1:
.endif
	rts

/* d6語を Word-RAM(a3) → VRAM(d3) へDMA。完了待ち。trashes d0,d2
   Word-RAM源はフェッチが1ワード遅延するため、src+2/full lengthを通常dstへDMAし、
   DMAが書かないdst先頭をCPUでa3の先頭ワードから修復する。 */
dma_chunk_wr:
	move.w	#0x8F02, (VDP_CTRL).l		/* autoinc=2 */
	move.w	d6, d2				/* 長さ = chunk 語 */
	move.w	#0x9300, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.w	#8, d2
	move.w	#0x9400, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	move.l	a3, d2				/* 源 = (src+2)/2 : 1ワード遅延の補正 */
	addq.l	#2, d2
	lsr.l	#1, d2
	move.w	#0x9500, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9600, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9700, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	/* Build the normal VRAM-write command once.  CD5 in its low word starts
	   DMA; the preserved command then restores the same destination for the
	   one-word CPU repair without recomputing set_vram_write. */
	move.l	d3, d0
	andi.l	#0x0000FFFF, d0
	move.l	d0, d2
	andi.l	#0x00003FFF, d0
	swap	d0
	ori.l	#0x40000000, d0
	lsr.w	#7, d2
	lsr.w	#7, d2
	andi.w	#0x0003, d2
	or.w	d2, d0				/* d0 = ordinary VRAM-write command */
	move.l	d0, d2				/* preserved across wait_dma_done */
	ori.w	#0x0080, d0			/* CD5: memory-to-VRAM DMA */
	move.l	d0, (VDP_CTRL).l		/* high control word, then CD5 trigger word */
	bsr	wait_dma_done
	/* 先頭1ワードはDMA開始ラッチの古い値(ゴミ)が書かれるため、CPUで上書き修復。
	   (src+2補正で2ワード目以降は正しい。ゴミはチャンク先頭の1ワードのみ) */
	move.l	d2, (VDP_CTRL).l
	move.w	(a3), (VDP_DATA).l
	rts

/* d6語を Main-RAM(a3) → VRAM(d3=バイトアドレス) へDMA。完了待ち。trashes d0,d2 */
dma_chunk:
	move.w	#0x8F02, (VDP_CTRL).l		/* autoinc=2 */
	move.w	d6, d2				/* 長さ 0x93/94 */
	move.w	#0x9300, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.w	#8, d2
	move.w	#0x9400, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	move.l	a3, d2				/* 源 = a3/2 (Main-RAM) */
	lsr.l	#1, d2
	move.w	#0x9500, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9600, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9700, d0
	or.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	move.l	d3, d0				/* dst=d3 コマンド(VRAM書込+CD5起動) */
	and.l	#0x0000FFFF, d0
	move.l	d0, d2
	andi.w	#0x3FFF, d2
	ori.w	#0x4000, d2
	move.w	d2, (VDP_CTRL).l
	move.l	d0, d2
	lsr.l	#8, d2
	lsr.l	#6, d2
	andi.w	#0x0003, d2
	ori.w	#0x0080, d2
	move.w	d2, (VDP_CTRL).l
	bsr	wait_dma_done
	rts

/* DMA完了待ち(status bit1)。trashes d0 */
wait_dma_done:
1:
	move.w	(VDP_CTRL).l, d0
	btst	#1, d0
	bne	1b
	rts

.ifdef NT_DMA_FLIP
/* Copy the complete 40x28 visible name-table aperture into the inactive back
   table with one Main-RAM DMA. Call inside the flip VBlank. The DEBUG readiness
   sample captured before the cadence wait is patched into the staged row
   immediately before the trigger so it belongs to the frame carried by this
   same DMA. trashes d0,d2,a0. */
nt_dma_flip:
	move.w	#0x8F02, (VDP_CTRL).l
	move.w	#0x9300|(NT_STAGE_WORDS&0xFF), (VDP_CTRL).l
	move.w	#0x9400|((NT_STAGE_WORDS>>8)&0xFF), (VDP_CTRL).l
	move.l	#nt_stage, d2
	lsr.l	#1, d2
	move.w	#0x9500, d0
	move.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9600, d0
	move.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9700, d0
	move.b	d2, d0
	move.w	d0, (VDP_CTRL).l
	moveq	#0, d0
	move.w	back_idx, d0
	lsl.l	#8, d0
	lsl.l	#5, d0
	add.l	#NT0, d0			/* back_base */
	move.l	d0, d2
	andi.l	#0x00003FFF, d0
	swap	d0
	ori.l	#0x40000000, d0
	lsr.w	#7, d2
	lsr.w	#7, d2
	andi.w	#0x0003, d2
	or.w	d2, d0
	ori.w	#0x0080, d0			/* CD5 */
.ifdef DEBUG
	move.w	nt_dma_ready_v, d2
	andi.w	#0x00FF, d2
	add.w	d2, d2
	add.w	d2, d2
	lea	dbg_hex_pairs, a0
	move.l	(a0,d2.w), nt_stage+(64+1)*2	/* logical cells 41-42 */
.endif
	move.l	d0, (VDP_CTRL).l
	bra	wait_dma_done
.endif

/* d0 = VRAM addr(<=0xFFFF) -> VDP_CTRL に write コマンド。trashes d0,d2 */
set_vram_write:
	move.l	d0, d2
	andi.l	#0x3FFF, d0
	swap	d0
	ori.l	#0x40000000, d0
	lsr.w	#7, d2
	lsr.w	#7, d2
	andi.w	#3, d2
	or.w	d2, d0
	move.l	d0, (VDP_CTRL).l
	rts

/* 初期CRAM = M-PALTAB[0](区間0)。ip_entry冒頭のコピー後ならいつでも呼べる。 */
load_movie_palette:
	move.l	#0xC0000000, (VDP_CTRL).l
	lea	PALTAB_RAM, a0
	move.w	#64-1, d0
1:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d0, 1b
	rts

.ifdef PLAYER_SPECIALIZED
/* Minimal preload display. The same 16 hexadecimal glyphs are permanently
   reserved immediately above the resident pool in DEBUG and release builds.
   NT1 row 0, columns 0..3 show loaded PrgBuf KiB as four hexadecimal digits. */
draw_startup:
	movem.l	d0-d2/a0, -(sp)
	bsr	load_movie_palette
	move.l	#HUD_FONT_ADDR, d0
	bsr	set_vram_write
	lea	dbgfont, a0
	move.w	#DBGFONT_N*16-1, d1
1:
	move.w	(a0)+, d0			/* each nibble is 0 or 1 */
	move.w	d0, d2
	lsl.w	#1, d2
	or.w	d2, d0
	lsl.w	#1, d2
	or.w	d2, d0
	lsl.w	#1, d2
	or.w	d2, d0			/* 1 -> 0xF independently in every nibble */
	ori.w	#0x1111, d0			/* 0 -> 0x1; 0xF remains 0xF */
	move.w	d0, (VDP_DATA).l
	dbra	d1, 1b
	moveq	#0, d0
	bsr	startup_write_hex
	movem.l	(sp)+, d0-d2/a0
	rts

/* d0.w = remaining 2-KiB PrgBuf preload sectors. Display loaded KiB. */
startup_update_prg:
	move.w	#PC_PREBUF_SEC, d4
	sub.w	d0, d4
	add.w	d4, d4			/* 2-KiB sectors -> KiB */
	move.w	d4, d0
	bra	startup_write_hex

/* d0.w = four hexadecimal digits written to NT1 row 0, columns 0..3. */
startup_write_hex:
	movem.l	d0-d2/d4, -(sp)
	move.w	d0, d4
	move.l	#NT1, d0
	bsr	set_vram_write
	move.w	d4, d0
	rol.w	#4, d0
	andi.w	#0x000F, d0
	addi.w	#HUD_FONT_VTILE, d0
	move.w	d0, (VDP_DATA).l
	move.w	d4, d0
	lsr.w	#8, d0
	andi.w	#0x000F, d0
	addi.w	#HUD_FONT_VTILE, d0
	move.w	d0, (VDP_DATA).l
	move.w	d4, d0
	lsr.w	#4, d0
	andi.w	#0x000F, d0
	addi.w	#HUD_FONT_VTILE, d0
	move.w	d0, (VDP_DATA).l
	andi.w	#0x000F, d4
	addi.w	#HUD_FONT_VTILE, d4
	move.w	d4, (VDP_DATA).l
	movem.l	(sp)+, d0-d2/d4
	rts

/* Initial-stream wait with live PrgBuf preload progress. COMSTAT1 is otherwise
   still free for boot errors and later desync diagnostics. */
cmd_wait_startup:
	move.w	d0, (GA_COMCMD0).l
	move.w	#0xFFFF, d5			/* last displayed remaining count */
1:
	move.w	(GA_COMSTAT0).l, d0
	cmp.w	#STAT_BOOT_STAGE, d0
	beq.s	6f
	cmp.w	#STAT_READY, d0
	beq.s	3f
	move.w	(GA_COMSTAT1).l, d0
	tst.w	d0				/* zero is shown only after STAT_READY */
	beq.s	7f
	cmp.w	d5, d0
	beq.s	7f
	move.w	d0, d5
	tst.w	d0				/* negative 0xBADx is directly displayable */
	bmi.s	5f
	bsr	startup_update_prg
	bra.s	7f
5:
	bsr	startup_write_hex
7:
	/* The counter is frame-paced: sample Sub once per VBlank instead of
	   hammering the gate-array registers in an unbounded Main-CPU loop. */
	bsr	wait_vblank
	bra	1b
6:
	bsr	consume_boot_stage
	move.w	#1, (GA_COMCMD1).l
6:
	tst.w	(GA_COMSTAT0).l
	bne.s	6b
	clr.w	(GA_COMCMD1).l
	bra	1b
3:
	moveq	#0, d0
	bsr	startup_update_prg
	rts					/* keep CMD_STREAM asserted through frame-0 flip */
.endif

consume_boot_stage:
	movem.l	d0-d7/a0-a6, -(sp)
	/* パレット表と切替表はIPイメージ内蔵(ip_entry冒頭でM-RAMへコピー済み)。
	   stageに残る内容はDic stagingとBVRM sidecarのみ。 */
.ifdef PLAYER_SPECIALIZED
.if (PC_FEATURES & 0x0008)
.if PC_DIC_PATTERNS > 0
	lea	(PROBE_BANK+DIC_STAGE_OFF).l, a1
	lea	DIC_BUF, a2
	move.w	#PC_DIC_PATTERNS*8-1, d1
1:
	move.l	(a1)+, (a2)+
	dbra	d1, 1b
.endif
.endif
.endif
	bsr	load_boot_vram_sidecar
	movem.l	(sp)+, d0-d7/a0-a6
	rts

cmd_wait_ready:
	move.w	d0, (GA_COMCMD0).l
1:
	move.w	(GA_COMSTAT0).l, d0
	cmp.w	#STAT_BOOT_STAGE, d0
	beq.s	4f
	cmp.w	#STAT_READY, d0
	bne	1b
	rts					/* one CMD_STREAM edge remains pending */
4:
	bsr	consume_boot_stage
	move.w	#1, (GA_COMCMD1).l
4:
	tst.w	(GA_COMSTAT0).l
	bne.s	4b
	clr.w	(GA_COMCMD1).l
	bra	1b

/* Frame 0 is already visible when this clears the sole startup command.
   Sub starts PCM and the continuous timed suffix on this edge, clears READY,
   then prepares frame 1 behind the ordinary CMD_SWAP wait. */
start_playback:
	move.w	#0, (GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	bne.s	1b
	rts
/* Boot-stage directory at stage+0x0FC0:
     "BVRM", count_A.w, count_B.w, count_C.w
   Records are [zero-based physical_slot.w, packed_pattern[32]] in three fixed
   holes around the directory: +0000..0F00, +1000..3000, and +5000..6000. */
load_boot_vram_sidecar:
	movem.l	d0-d7/a0-a2, -(sp)
	lea	(PROBE_BANK+STATUS_OFF+0x80).l, a0
	btst	#FEATURE_BOOT_VRAM_SIDECAR_BIT, 63(a0)
	beq	9f
	lea	(PROBE_BANK+BOOT_VRAM_DIR_OFF).l, a2
	cmpi.l	#BOOT_VRAM_MAGIC, (a2)
	bne	9f
	move.w	4(a2), d7
	cmpi.w	#0x0F00/34, d7
	bls.s	1f
	move.w	#0x0F00/34, d7
1:
	lea	(PROBE_BANK).l, a1
	bsr	load_boot_vram_records

	move.w	6(a2), d7
	cmpi.w	#0x2000/34, d7
	bls.s	2f
	move.w	#0x2000/34, d7
2:
	lea	(PROBE_BANK+0x1000).l, a1
	bsr	load_boot_vram_records
	move.w	8(a2), d7
	cmpi.w	#0x1000/34, d7
	bls.s	3f
	move.w	#0x1000/34, d7
3:
	lea	(PROBE_BANK+0x5000).l, a1
	bsr	load_boot_vram_records
9:
	movem.l	(sp)+, d0-d7/a0-a2
	rts

/* a1=record cursor, d7=count, a0=O_HDR. */
load_boot_vram_records:
	tst.w	d7
	beq.s	8f
	subq.w	#1, d7
4:
	moveq	#0, d0
	move.w	(a1)+, d0			/* zero-based physical slot */
	cmp.w	14(a0), d0
	bhs.s	6f
	add.w	16(a0), d0			/* + resident pool base */
	lsl.l	#5, d0
	bsr	set_vram_write
	moveq	#8-1, d1
5:
	move.l	(a1)+, (VDP_DATA).l
	dbra	d1, 5b
	bra.s	7f
6:
	adda.w	#32, a1
7:
	dbra	d7, 4b
8:
	rts

/* CMD_SWAP送信 → STAT_READY(通常) か STAT_END(映画終端) を待つ。d0=受けたSTAT */
swap_or_end:
.ifdef DEBUG
	move.w	(VDP_HV).l, d1
	lsr.w	#8, d1				/* V-counter at CMD_SWAP request */
.endif
	move.w	#CMD_SWAP, (GA_COMCMD0).l
1:
	move.w	(GA_COMSTAT0).l, d0
	cmp.w	#STAT_READY, d0
	beq	2f
	cmp.w	#STAT_END, d0
	bne	1b
2:
	move.w	d0, d3				/* preserve READY/END across cadence polling */
.ifdef DEBUG
	move.w	(VDP_HV).l, d2
	lsr.w	#8, d2
	sub.w	d1, d2
	andi.w	#0x00FF, d2			/* approximate elapsed scanlines */
	move.w	d2, sub_wait_lines
.endif
	move.w	#0, (GA_COMCMD0).l
3:
	tst.w	(GA_COMSTAT0).l
	bne	3b
	move.w	d3, d0				/* swap_or_end return contract */
	rts

/* Display the player-only frame -1 while frame 0 is built. It is a black movie
   plane; DEBUG overlays the complete ordinary HUD with frame=FFFF. The visible
   name table is back_idx^1 because back_idx always names the next build target. */
show_frame_minus_one:
	movem.l	d0-d2, -(sp)
	move.w	#0x8134, (VDP_CTRL).l		/* display off; keep VInt, DMA and mode 5 */
	moveq	#0, d0
	move.w	back_idx, d0
	eori.w	#1, d0
	lsl.l	#8, d0
	lsl.l	#5, d0
	add.l	#NT0, d0
	bsr	set_vram_write
	moveq	#0, d0
	move.w	#64*32-1, d1
1:
	move.w	d0, (VDP_DATA).l
	dbra	d1, 1b
.ifdef DEBUG
	move.w	#-1, frame_no
	eori.w	#1, back_idx			/* publish_dbg target = visible plane */
	bsr	prepare_dbg
	bsr	publish_dbg
	eori.w	#1, back_idx
.endif
	move.w	#0x8174, (VDP_CTRL).l		/* display on + VInt + DMA + mode 5 */
	bsr	wait_vblank			/* make FFFF visible in at least one capture field */
	movem.l	(sp)+, d0-d2
	rts

wait_vblank:
	move.w	d1, -(sp)
1:
	move.w	(VDP_CTRL).l, d1
	btst	#3, d1
	beq	1b
2:
	move.w	(VDP_CTRL).l, d1
	btst	#3, d1
	bne	2b
	move.w	(sp)+, d1
	rts

/* Build the values-only HUD rows in Main RAM before the display deadline.
   Publishing the finished rows into the inactive Plane A table is a short fixed
   copy; reg2 selects the completed picture and HUD atomically.
   Category glyphs are omitted to reserve cells for future supply metrics.
   The 43-word layout uses four frame digits; one digit each for palette,
   slip, desync, resync and CD wait; two for audio lead, Sub wait and ADPCM;
   four for packed VBlank-spill/transfer ticks; two for runs and PrgBuf jitter;
   then flip/share/delay, packed pump-gap/back-pressure, one-digit MSF gap,
   packed reader lead/slot, transfer-VBlank count, transfer-end V-counter,
   pattern-DMA start V-counter and name-table-DMA start V-counter.
   H32 wraps after 32 words; H40 wraps after 40 words. */
prepare_dbg:
.ifdef HUD_HEX_TABLE
	movem.l	d0-d4/a0-a1, -(sp)
	lea	dbg_hex_pairs, a1
.else
	movem.l	d0-d4/a0, -(sp)
.endif
	lea	dbg_row, a0
	/* frame number, 4 digits */
	move.w	frame_no, d4
	DBG_PUT4
	/* palette segment, low nibble */
	move.w	dbg_seg, d4
	DBG_PUT1
	/* slip/reseek count, low nibble */
	move.w	(PROBE_BANK+STATUS_OFF+0x00).l, d4
	DBG_PUT1
	/* desync count, low nibble */
	move.w	(PROBE_BANK+STATUS_OFF+0x7E).l, d4
	DBG_PUT1
	/* audio re-sync count, low nibble */
	move.w	(PROBE_BANK+STATUS_OFF+0x20).l, d4
	DBG_PUT1
	/* current audio lead high byte (256-byte units) */
	move.w	(PROBE_BANK+STATUS_OFF+0x22).l, d4
	lsr.w	#8, d4
	DBG_PUT2
	/* total blocking CD pumps (current control + older BODY slot) */
	move.w	(PROBE_BANK+STATUS_OFF+0x18).l, d4
	add.w	(PROBE_BANK+STATUS_OFF+0x1A).l, d4
	DBG_PUT1
	/* Main's CMD_SWAP wait for Sub completion, in approximate scanlines */
	move.w	sub_wait_lines, d4
	DBG_PUT2
	/* Sub ADPCM decode time in 4*30.72us units (zero for PCM builds). */
	move.w	(PROBE_BANK+STATUS_OFF+0x1C).l, d4
	lsr.w	#2, d4
	DBG_PUT2
	/* Pack the one-digit Main VBlank spill into the unused high nibble of
	   the 12-bit pattern-transfer stopwatch. */
	move.w	dma_elapsed_ticks, d4
	andi.w	#0x0FFF, d4
	move.w	frame_vblank_waits, d0
	andi.w	#0x000F, d0
	ror.w	#4, d0
	or.w	d0, d4
	DBG_PUT4
	move.w	n_runs, d4
	DBG_PUT2
	/* COMSTAT2 holds Sub's exact sticky high-water occupancy in patterns.
	   Convert only the excess above the fps-specific normal PrgBuf cap, rounding
	   upward so any use of the physical jitter reserve displays J>=01. */
	move.w	(GA_COMSTAT2).l, d4
.ifdef PLAYER_SPECIALIZED
	cmp.w	#PC_PRG_BUF_CAP_PATTERNS, d4
	bls.s	1f
	sub.w	#PC_PRG_BUF_CAP_PATTERNS, d4
.else
	cmp.w	md_prg_buf_cap_patterns, d4
	bls.s	1f
	sub.w	md_prg_buf_cap_patterns, d4
.endif
	add.w	#31, d4
	lsr.w	#5, d4				/* 32 patterns = 1 KiB */
	bra.s	2f
1:
	moveq	#0, d4
2:
	DBG_PUT2
.ifdef HUD_FLIP_FIELDS
	/* V: V-counter at the previous accepted flip (this row is built before
	   its own frame's flip, so the freshest sample is one frame old). */
	move.w	flip_hv_v, d4
	DBG_PUT2
	/* O: V-counter immediately after VBlank budget 1's pattern work. */
	move.w	pattern_vblank1_exit_v, d4
	DBG_PUT2
	/* E: this frame's Pass2 entry delay since the previous flip, ticks/4 */
	move.w	pass2_entry_q, d4
	DBG_PUT2
.ifdef HUD_SUB_POLL_GAP
	/* G: maximum time spent outside the Sub CDC pump between service
	   opportunities during this frame, in 30.72 us stopwatch ticks. Bit 15
	   carries B when APPLY back-pressure rejected a control-sector pump.
	   Sub stores B in CTRLWAIT's unused high-byte sign bit so it cannot
	   interfere with the running G maximum. */
	move.w	(PROBE_BANK+STATUS_OFF+0x26).l, d4
	tst.b	(PROBE_BANK+STATUS_OFF+0x18).l
	bpl.s	9f
	ori.w	#0x8000, d4
9:
	DBG_PUT4
	/* Cumulative MSF sequence-gap recoveries, low nibble. */
	move.w	(PROBE_BANK+STATUS_OFF+0x00).l, d4
	lsr.w	#8, d4
	DBG_PUT1
	/* CD reader lead: one nibble of complete frame slots followed by one
	   nibble of sector position inside the current physical slot. */
	move.w	(PROBE_BANK+STATUS_OFF+0x2A).l, d4
	move.w	d4, d3
	lsr.w	#8, d4
	DBG_PUT1
	move.w	d3, d4
	DBG_PUT1
	/* Number of fresh VBlank budgets opened and V-counter when Pass2
	   pattern transfer ended, before HUD/NT/CRAM/flip work. */
	move.w	pattern_transfer_vblanks, d4
	DBG_PUT1
	move.w	pattern_exit_v, d4
	DBG_PUT2
	/* Raw V-counters when the first pattern run is ready before its fresh-blank
	   wait, and when the H40 name-table path is ready before its cadence-final
	   VBlank wait. A frame with no pattern run or no NT-DMA path retains zero
	   for that field. */
	move.w	pattern_dma_ready_v, d4
	DBG_PUT2
	move.w	nt_dma_ready_v, d4
	DBG_PUT2
.endif
.endif
.ifdef HUD_HEX_TABLE
	movem.l	(sp)+, d0-d4/a0-a1
.else
	movem.l	(sp)+, d0-d4/a0
.endif
	rts

.ifdef DEBUG
.ifdef NT_DMA_FLIP
/* Merge the final H40 HUD into the 64-entry-pitch Main-RAM name-table stage.
   This runs after the shared-blank admission check but before its one NT DMA,
   replacing the slower post-DMA VDP-port republish. Trashes d0/a0/a1. */
stamp_dbg_stage:
	lea	dbg_row, a0
	lea	nt_stage, a1
	moveq	#20-1, d0			/* H40 row 0: first 40 words */
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b
	lea	nt_stage+64*2, a1		/* H40 row 1: remaining three words */
	move.l	(a0)+, (a1)+
	move.w	(a0)+, (a1)+
	rts
.endif
.endif

/* Publish a prebuilt row over the first cells of the inactive Plane A movie
   table. It is not displayed yet, so the copy is safe during active display.
   Cells to the right remain the exact same movie table; no Window/Plane B
   transparency or stale alternate frame is involved. */
publish_dbg:
	movem.l	d0-d1/a0, -(sp)
	moveq	#0, d0
	move.w	back_idx, d0
	lsl.l	#8, d0
	lsl.l	#5, d0				/* back_idx*0x2000 */
	add.l	#NT0, d0
	bsr	set_vram_write
	lea	dbg_row, a0
.ifdef PLAYER_SPECIALIZED
.ifdef HUD_FLIP_FIELDS
.if PC_MODE == 0
	.rept 16				/* H32 row 0: first 32 words */
	move.l	(a0)+, (VDP_DATA).l
	.endr
.else
	.rept 20				/* H40 row 0: first 40 words */
	move.l	(a0)+, (VDP_DATA).l
	.endr
.endif
.ifdef HUD_SUB_POLL_GAP
	/* Name tables use a 64-cell pitch. Resume the linear 43-cell stream at
	   logical cell 32 for H32 and logical cell 40 for H40. */
	moveq	#0, d0
	move.w	back_idx, d0
	lsl.l	#8, d0
	lsl.l	#5, d0
	add.l	#NT0+0x80, d0
	bsr	set_vram_write
.if PC_MODE == 0
	.rept 5				/* H32 row 1: first ten of eleven words */
	move.l	(a0)+, (VDP_DATA).l
	.endr
	move.w	(a0)+, (VDP_DATA).l
.else
	move.l	(a0)+, (VDP_DATA).l		/* H40 row 1: first two of three words */
	move.w	(a0)+, (VDP_DATA).l
.endif
.endif
.else
	.rept 15
	move.l	(a0)+, (VDP_DATA).l
	.endr
.endif
.else
	moveq	#15-1, d1			/* common H32/H40 row: 30 words */
1:
	move.l	(a0)+, (VDP_DATA).l
	dbra	d1, 1b
.endif
	movem.l	(sp)+, d0-d1/a0
	rts

/* Append four value digits to the prebuilt row.  Reuse the straight byte-pair
   formatter instead of walking four nibbles through a DBRA loop. */
dbg_put4:
	move.w	d4, d3
	lsr.w	#8, d4
	bsr	dbg_put2
	move.w	d3, d4
	bra	dbg_put2

/* Append three/one hexadecimal digits for the exact split counters. */
dbg_put3:
	move.w	d4, d3
	lsr.w	#8, d4
	bsr	dbg_put1
	move.w	d3, d4
	bra	dbg_put2

.ifdef HUD_HEX_TABLE
/* Compact specialized three-digit formatter shared by prepare_dbg and the
   final staged-HUD patch. a1 is the 256-entry byte-pair table. */
dbg_fast_put3:
	move.w	d4, d3
	lsr.w	#8, d4
	bsr	dbg_put1
	move.w	d3, d4
	andi.w	#0x00FF, d4
	add.w	d4, d4
	add.w	d4, d4
	move.l	(a1,d4.w), (a0)+
	rts
.endif

dbg_put1:
	andi.w	#0xF, d4
	addi.w	#HUD_FONT_VTILE, d4
	move.w	d4, (a0)+
	rts

/* Append the low byte as two digits.  Calculate both name-table words directly;
   this is the hot DEBUG formatter and avoids a per-nibble loop and DBRA. */
dbg_put2:
	move.w	d4, d0
	andi.w	#0xF, d0
	addi.w	#HUD_FONT_VTILE, d0
	move.w	d0, 2(a0)			/* low nibble */
	lsr.w	#4, d4
	andi.w	#0xF, d4
	addi.w	#HUD_FONT_VTILE, d4
	move.w	d4, (a0)			/* high nibble */
	addq.l	#4, a0
	rts

/* パレット表(全区間)と切替表はboot時にM-RAMへ写すだけの一時データなので、
   codegenが上書きする.startup領域に置いて恒久.dataの8KiB枠を消費しない。 */
	.section .startup, "a", @progbits
	.align 2
paltab_image:
	.incbin "paltab.bin"
paltab_image_end:
.if (paltab_image_end-paltab_image) % 128
	.error "paltab.bin must be n_seg*128 bytes"
.endif
.if (paltab_image_end-paltab_image) > PALTAB_MAX_SEG*128
	.error "paltab.bin exceeds the fixed M-PALTAB capacity"
.endif
palidx_image:
	.incbin "palidx.bin"
.if .-palidx_image != PALIDX_ENTRIES*4
	.error "palidx.bin must be 16 entries of 4 bytes"
.endif

	.data
	.align 2
dbgfont:
	.incbin "dbgfont.bin"
.ifdef HUD_HEX_TABLE
/* Longword order matches two consecutive VDP name-table writes.  This table
   remains in the permanent IP image; it does not consume DicBuf capacity. */
	.align 2
dbg_hex_pairs:
	.set dbg_hex_byte, 0
	.rept 256
	.word HUD_FONT_VTILE + ((dbg_hex_byte >> 4) & 0x0F)
	.word HUD_FONT_VTILE + (dbg_hex_byte & 0x0F)
	.set dbg_hex_byte, dbg_hex_byte + 1
	.endr
.endif
/* The HUD font must fit entirely inside the 0xD000-0xDFFF gap (NT0..NT1). */
.if (HUD_FONT_VTILE < NT0/32) || (HUD_FONT_VTILE + DBGFONT_N > NT1/32)
	.error "hexadecimal font must fit in the 0xD000-0xDFFF gap"
.endif

	.bss
	.align 2
shadow:
	.space 0x1000				/* logical H40=2240B; padded for bounded list offsets */
dbg_row:
.ifdef HUD_SUB_POLL_GAP
	.space HUD_COMBINED_WORDS*2		/* H32 wraps; H40 fits one row */
.else
	.space 40*2				/* prebuilt values-only row; H40 DEBUG fills all 40 cells */
.endif
nt_stage:
	.space 64*28*2				/* zero-bordered visible H40 staging for flip-blank DMA */
.ifndef PLAYER_SPECIALIZED
md_mode:
	.space 2
md_vsync_n:
	.space 2				/* v4: 1コマの表示VBLANK数(15fps=4, 30fps=2) */
md_fixed_n:
	.space 2				/* feature bit 1; 24fps N2 hint alone stays unpaced */
md_pace_arm_ticks:
	.space 2				/* stopwatch arm point between VBlank N-1 and N */
.endif
vsync_acc:
	.space 2				/* v4: 現コマで消費したVBLANK数(ペーシング用) */
pace_flip_tick:
	.space 2				/* GA stopwatch tick at preceding fixed-N flip */
.ifndef PLAYER_SPECIALIZED
md_tcols:
	.space 2
md_trows:
	.space 2
md_bmbytes:
	.space 2				/* ceil(cells/8); supported grids divide exactly */
md_row0:
	.space 2
md_col0:
	.space 2
md_vbudget:
	.space 2
md_prg_buf_cap_patterns:
	.space 2				/* fps-scaled normal PrgBuf ceiling for DEBUG J */
.endif
back_idx:
	.space 2
frame_no:
	.space 2
started:
	.space 2
n_runs:
	.space 2
dbg_seg:
	.space 2
palidx_ptr:
	.space 4				/* next unconsumed M-PALIDX switch entry */
sub_wait_lines:
	.space 2				/* DEBUG sub_wait_scanlines */
frame_vblank_waits:
	.space 2				/* DEBUG vblank_spill snapshot before display pacing */
dma_elapsed_ticks:
	.space 2				/* DEBUG Uxxxx: 30.72 us stopwatch ticks */
dma_start_tick:
	.space 2				/* DEBUG stopwatch sample at first pattern transfer */
vbudget_from_head:
	.space 2				/* current d7 began at a proven VBlank head */
pattern_final_reserve_words:
	.space 2				/* cadence-final NT/HUD/CRAM/flip DMA-equivalent cost */
vbudget_held_reserve:
	.space 2				/* final capacity withheld from the current pattern d7 */
flip_hv_v:
	.space 2				/* DEBUG flip_vcounter */
pattern_vblank1_exit_v:
	.space 2				/* DEBUG first_share_exit_vcounter */
pass2_entry_q:
	.space 2				/* DEBUG pass2_delay_q4 */
pattern_vblank1_words:
	.space 2				/* internal pattern words in budget 1 */
pattern_vblank2_words:
	.space 2				/* internal pattern words in budget 2 */
pattern_vblank3_words:
	.space 2				/* internal pattern words in budget 3 */
pattern_vblank4_words:
	.space 2				/* internal pattern words in budget 4 */
pattern_transfer_vblanks:
	.space 2				/* runtime budget index; DEBUG transfer_vblanks */
pattern_exit_v:
	.space 2				/* DEBUG transfer_end_vcounter */
pattern_dma_ready_v:
	.space 2				/* DEBUG pattern_dma_ready_vcounter */
nt_dma_ready_v:
	.space 2				/* DEBUG name_table_dma_ready_vcounter */
.ifdef MAIN_CODEGEN
md_codegen:
	.space 2				/* 1 only after the complete runtime proof succeeds */
md_codegen_blit:
	.space 2				/* Phase 2 geometry/range proof succeeded */
md_codegen_blit_addr:
	.space 8				/* NT0 and NT1 generated entry addresses */
md_codegen_end:
	.space 4				/* generated end address, including failed attempts */
.endif
