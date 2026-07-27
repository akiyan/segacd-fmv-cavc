/*
 * Phase B5: TTRC delta-stream player, Sub CPU side.
 *
 * HEADER.DAT contains only static boot state through PREBUFFER. BODY.DAT begins
 * with an untimed arm prefix (audio + frame-0 control/patterns), followed by the
 * timed frame-1+ stream. The arm and playback clocks are intentionally distinct.
 *
 * During the timed read, each frame places control sectors first, then payload
 * sectors, then rate padding.  Control feeds the apply ring and payload feeds
 * the PRG-RAM pattern ring.  Each control
 * block is linearized in Word RAM, expanded to Main-CPU output, paired with
 * decoded ADPCM audio and handed over by a 1M Word-RAM bank swap.
 */

.equ CDBIOS,      0x00005F22
.equ CDB_STAT,    0x00005E80
.equ BIOS_DRV_INIT, 0x0010
.equ BIOS_CDB_STAT, 0x0081
.equ BIOS_CDC_STOP, 0x0089
.equ BIOS_CDC_STAT, 0x008A
.equ BIOS_CDC_READ, 0x008B
.equ BIOS_CDC_TRN,  0x008C
.equ BIOS_CDC_ACK,  0x008D
.equ BIOS_ROM_READN,0x0020

.ifdef PLAYER_SPECIALIZED
	.include "player_constants.inc"
.if (PC_FEATURES & 0x0008)
.equ INCLUDE_PATTERN_SUPPLY, 1
.endif
.if (PC_FEATURES & 0x0100)
.equ INCLUDE_WORDBUF_RING, 1
.endif
.endif
	.include "sp_extension.inc"

/* The packed cold-run parser is used by every unified pattern-supply stream
   and by the dense 24/30fps cadence.  A legacy lower-rate plain-Prg diagnostic
   build may still omit it to preserve the entry walker. */
.ifdef INCLUDE_PATTERN_SUPPLY
.equ INCLUDE_COLD_RUN_FASTPATH, 1
.else
.ifdef PLAYER_SPECIALIZED
.if PC_PUMP_MASK == 0x03FF
.equ INCLUDE_COLD_RUN_FASTPATH, 1
.endif
.else
.equ INCLUDE_COLD_RUN_FASTPATH, 1
.endif
.endif

.ifdef DEBUG
.ifdef PLAYER_SPECIALIZED
.equ DEBUG_PRGBUF_Q, 1
.if PC_PUMP_MASK == 0x03FF
.equ DEBUG_PRGMIN_DIRECT, 1
.endif
.equ DEBUG_SUB_POLL_GAP, 1
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

.macro PC_SUB_W runtime, constant, dest
.ifdef PLAYER_SPECIALIZED
	subi.w	#\constant, \dest
.else
	sub.w	\runtime, \dest
.endif
.endm

.macro PC_AND_W runtime, constant, dest
.ifdef PLAYER_SPECIALIZED
	andi.w	#\constant, \dest
.else
	and.w	\runtime, \dest
.endif
.endm

.equ SUB_GA_BASE, 0x00FF8000
.equ MEMMODE,     SUB_GA_BASE+0x0002
.equ COMCMD0,     SUB_GA_BASE+0x0010
.equ COMCMD1,     SUB_GA_BASE+0x0012
.equ COMSTAT0,    SUB_GA_BASE+0x0020
.equ COMSTAT1,    SUB_GA_BASE+0x0022
.equ COMSTAT2,    SUB_GA_BASE+0x0024
.equ GA_STOPWATCH,SUB_GA_BASE+0x000C    /* 12-bit, 30.72us/tick */
/* The 68000 absolute-word form sign-extends 0x800C to the same 24-bit bus
   address and saves two bytes in the DEBUG diagnostic image. */
.equ GA_STOPWATCH_ABS_W,GA_STOPWATCH-0x01000000

.equ SUB_BANK_1M, 0x000C0000

/* --- TTRC v18 BODY-arm/routing contract (checked by tools/check_player_ring.py) --- */
.equ ROUTING_VERSION,       18
.ifdef PLAYER_SPECIALIZED
.equ ROUTING_BYTES,         PC_ROUTING_BYTES
.else
.equ ROUTING_BYTES,         16384
.endif
.equ ROUTING_MAX_FRAMES,    16384
.equ ROUTING_SECTOR_BYTES,  2048
.equ ROUTING_SECTOR_SHIFT_A,8
.equ ROUTING_SECTOR_SHIFT_B,3
.equ ROUTING_CTRL_MASK,     0x0007
.equ ROUTING_CTRL_COUNT_MASK,0x0003
.equ ROUTING_WORD4_FLAG,    0x0004
.equ ROUTING_TOTAL_SHIFT,   3
.equ ROUTING_TOTAL_MASK,    0x0038
.equ ROUTING_WORD_SHIFT,    6
.equ ROUTING_WORD_MASK,     0x00C0
.equ ROUTING_MAX_ENTRY,     0x00ED
.equ FEATURE_COLD_RUNS_BIT, 0
.equ FEATURE_FIXED_N_BIT,   1
.equ FEATURE_PATTERN_SUPPLY_BIT, 3
.equ FEATURE_SHADOW_UPDATE_LISTS_BIT, 4
.equ FEATURE_VRAM_RAW_PREFETCH_BIT, 5
.equ FEATURE_DICBUF_INDEXED_RUNS_BIT, 6
.equ FEATURE_BOOT_VRAM_SIDECAR_BIT, 7
.equ FEATURE_WORDBUF_RING_BIT, 8
.equ SHADOW_UPDATE_LIST_BIT, 15
.equ SHADOW_UPDATE_COUNT_MASK, 0x7FFF
.ifdef PLAYER_SPECIALIZED
.equ ROUTING_COPY_LONGS,    PC_ROUTING_COPY_LONGS
.else
.equ ROUTING_COPY_LONGS,    4096
.endif
.equ ROUTING_BANK_COPIES,   2

/* --- PRG-RAM layout --- */
/* The BIOS loads this resident image at 0x6000. ISO directory discovery uses
   the timed-ring tail only during boot, before any PrgBuf/frame-0 owner exists,
   so the initial SP may extend beyond the former 4 KiB project layout. */
.equ ISO_BUF,     0x00067000
.equ ISO_BUF_BYTES, 0x00010000
.equ SUB_PRG_SAFE_BASE, 0x00008000
.equ SUB_PRG_SAFE_END,  0x00009800
.equ PCM_DEC_BUF,       0x00008000  /* Sub専用decoded PCM scratch。Word-RAM DMAと競合させない */
.equ PCM_DEC_BUF_BYTES, 0x00000600
.equ PCM_DEC_BUF_END,   0x00008600
.equ WORD_PENDING0,     0x00008600  /* bank待ちWord sectorをCDCから退避するSub専用scratch */
.equ WORD_PENDING1,     0x00008E00
.equ WORD_PENDING_SAFE_END,0x00009600
.equ WORD_PENDING3,     0x00076800  /* boot extension tail; timed playback may reuse it */
.equ ADPCM_INDICES,     0x0000C000  /* 89*16 u16 new-index*32 */
.equ ADPCM_INDEX_BYTES, 0x00000B20
.equ ADPCM_INDICES_END, 0x0000CB20
.equ ADPCM_LUT,         0x0000CB20  /* offset-high -> RF5C164 sign-magnitude */
.equ ADPCM_LUT_BYTES,   0x00000100
.equ ADPCM_LUT_END,     0x0000CC20
.equ ADPCM_BOOT_COPY,   0x00076800
.equ ADPCM_BOOT_COPY_BYTES, 0x0058
.equ ADPCM_BOOT_COPY_LONGS, ADPCM_BOOT_COPY_BYTES/4
.if PCM_DEC_BUF < SUB_PRG_SAFE_BASE
.error "PCM_DEC_BUF begins below the marker-verified Sub PRG range"
.endif
.if PCM_DEC_BUF_END > SUB_PRG_SAFE_END
.error "PCM_DEC_BUF exceeds the marker-verified Sub PRG range"
.endif
.if WORD_PENDING0 != PCM_DEC_BUF_END
.error "Word pending scratch must follow PCM_DEC_BUF"
.endif
.if WORD_PENDING_SAFE_END > SUB_PRG_SAFE_END
.error "Word pending scratch exceeds the marker-verified Sub PRG range"
.endif
.if ADPCM_INDICES_END != ADPCM_LUT
.error "ADPCM output LUT does not follow the index table"
.endif
.if ADPCM_LUT_END > 0x0000D000
.error "hot ADPCM tables exceed their reserved PrgBuf page"
.endif
.if ISO_BUF+ISO_BUF_BYTES > 0x00077000
.error "boot ISO directory scratch overlaps timed APPLY"
.endif
.if SP_EXTENSION_EXEC_BASE != ADPCM_BOOT_COPY
.error "loaded Sub extension address differs from ADPCM_BOOT_COPY"
.endif
.if SP_EXTENSION_EXEC_BASE+SP_EXTENSION_BYTES > 0x00077000
.error "loaded Sub extension exceeds the boot-time PrgBuf tail"
.endif
.equ SP_STACK,    0x0007FF00        /* スタック最上位(apply端0x7F800の上, 1.8KB) */
/* 0x9800-0xC000は連続読み中にBIOSが踏む。0xC000の4KBはhot table、RINGは0xD000から。 */
.equ RING_BASE,   0x0000D000
.equ RING_SIZE,   0x00069800        /* 422KB。末尾2KBは4本目のbank待ちWord sector */
.equ RING_END,    RING_BASE+RING_SIZE     /* 0x76800 = WORD_PENDING3 */
.equ RING_PATTERNS, RING_SIZE/32
.equ F0PAT_TMP,   0x00072000        /* boot限定: H40最大1120 patterns=36KBを固定scratchから
                                       未使用APPLY先頭まで連続配置し、BODY前に展開する。 */
.equ APPLY_BASE,  0x00077000
.equ APPLY_SIZE,  0x00008800        /* 34KB(16KBは頭詰まり→滑りを実測。42KB→34KBはrouting移設分) */
.equ APPLY_END,   APPLY_BASE+APPLY_SIZE   /* 0x7F800 */
.equ ROUTING_TMP, 0x0007B000        /* boot限定。最大frame0 staging直後の未使用APPLY 16KB */
.if RING_END != WORD_PENDING3
.error "fourth pending Word sector must begin at the physical PrgBuf end"
.endif
.if WORD_PENDING3+0x800 != APPLY_BASE
.error "fourth pending Word sector must end at APPLY_BASE"
.endif

/* --- Word-RAM compact tail (same offsets in both physical banks) --- */
.ifdef PLAYER_SPECIALIZED
.equ CTRL_SCR,    SUB_BANK_1M+PC_CTRL_SCR_OFFSET
.equ PAD_SCR,     SUB_BANK_1M+PC_PAD_SCR_OFFSET
.equ ADPCM_TABLE, SUB_BANK_1M+PC_ADPCM_TABLE_OFFSET
.equ WORD_BUF0,   SUB_BANK_1M+PC_WR0_OFFSET
.equ WORD_BUF1,   SUB_BANK_1M+PC_WR1_OFFSET
.equ WORD_BUF0_END,SUB_BANK_1M+PC_WR0_END
.equ WORD_BUF1_END,SUB_BANK_1M+PC_WR1_END
.equ WORD_BUF0_CAP,PC_WR0_CAPACITY
.equ WORD_BUF1_CAP,PC_WR1_CAPACITY
.equ ROUTING,     SUB_BANK_1M+PC_ROUTING_OFFSET
.equ O_STATUS,    SUB_BANK_1M+PC_STATUS_OFFSET
.else
.equ CTRL_SCR,    0x000D0000
.equ PAD_SCR,     0x000D2000
.equ ADPCM_TABLE, 0x000D2800
.equ WORD_BUF0,   0x000D5200
.equ WORD_BUF1,   0x000D5200
.equ WORD_BUF0_END,0x000DC000
.equ WORD_BUF1_END,0x000DC000
.equ WORD_BUF0_CAP,(WORD_BUF0_END-WORD_BUF0)/32
.equ WORD_BUF1_CAP,(WORD_BUF1_END-WORD_BUF1)/32
.equ ROUTING,     0x000DC000
.equ O_STATUS,    SUB_BANK_1M+0xAF00
.endif
/* PC_PCM_DEC_BUF_OFFSET / generic +0x14C00 and the index/LUT portions of
   ADPCM_TABLE remain unused A/B-stable Word-RAM reserves. Timed decode uses
   only the signed deltas from Word RAM; the other hot data is Sub PRG above. */
.equ ADPCM_DELTAS, ADPCM_TABLE+2848 /* 89*16 s32 signed delta = 5696B */
.equ ADPCM_TABLE_BYTES, 8800
.equ ADPCM_DELTA_BYTES, 5696
.equ ADPCM_TABLE_SECTORS, 5
.equ ADPCM_BANK_COPIES, 2
.if SP_EXTENSION_LOAD_BASE != ROUTING_TMP+ADPCM_TABLE_BYTES
.error "Sub extension preload must follow the ADPCM table image"
.endif
.if SP_EXTENSION_BYTES > ADPCM_TABLE_SECTORS*0x800-ADPCM_TABLE_BYTES
.error "Sub extension exceeds the existing ADPCM sector padding"
.endif
.if SP_EXTENSION_BYTES < ADPCM_BOOT_COPY_BYTES
.error "Sub extension does not contain the complete qualified ADPCM entry"
.endif
.ifdef PLAYER_SPECIALIZED
.if PC_ROUTING_SEC <= 4
/* Up to 8 KiB of routing ends at ROUTING_TMP+0x2000.  The extension begins at
   ROUTING_TMP+8,800, leaving its second entry intact until prebuffer completes. */
.equ ROUTING_EXTENSION_IN_STAGE, 1
.endif
.endif

/* --- Word-RAM 出力(MDが読む) ---
   O_UPDS is absent: Main re-walks CTRL_SCR directly. The generated Wr0/Wr1
   starts reserve the complete parity-specific O_LOADS peak before WordBuf. */
.equ O_PALW,   SUB_BANK_1M+0x0000
.equ O_NLOAD,  SUB_BANK_1M+0x0002
.equ O_LOADS,  SUB_BANK_1M+0x0004
.equ O_SLIP,   O_STATUS+0x00
.equ O_DSY,    O_STATUS+0x7E
.equ O_CTRLWAIT,O_STATUS+0x18
.equ O_BODYWAIT,O_STATUS+0x1A
.equ O_AUDIOLEFT,O_STATUS+0x1C
.equ O_RESYNC, O_STATUS+0x20
.equ O_LEAD,   O_STATUS+0x22
.ifdef DEBUG_PRGBUF_Q
.equ O_PRGMIN, O_STATUS+0x24
.endif
.ifdef DEBUG_SUB_POLL_GAP
.equ O_PUMPGAP,O_STATUS+0x26
.endif
.equ O_HDR,    O_STATUS+0x80
.equ PALTAB_STAGE_OFF, 0x0000
.equ PALTAB_OFF, 0x1000
.equ PALTAB_STAGE_BYTES, 0x6000
.equ O_PALTAB_STAGE, SUB_BANK_1M+PALTAB_STAGE_OFF
.equ O_PALTAB, SUB_BANK_1M+PALTAB_OFF
.equ DIC_STAGE_OFF, 0x6000
.equ DIC_STAGE, SUB_BANK_1M+DIC_STAGE_OFF
.equ DIC_STAGE_PATTERNS, 256

/* --- RF5C164 output reconstructed from ADPCM --- */
.equ PCM_ENV,   0x00FF0001
.equ PCM_PAN,   0x00FF0003
.equ PCM_FDL,   0x00FF0005
.equ PCM_FDH,   0x00FF0007
.equ PCM_LSL,   0x00FF0009
.equ PCM_LSH,   0x00FF000B
.equ PCM_ST,    0x00FF000D
.equ PCM_CTRL,  0x00FF000F
.equ PCM_ONOFF, 0x00FF0011
.equ PCM_WAVE,  0x00FF2001
.equ PCM_PLAY_H, 0x00FF0023
.equ WAVE_RING_END, 0x8000
.equ RING_MASK, WAVE_RING_END-1
/* 音声リード: 起動時から先行書き込み位置(SYNC_LEAD)で再生を開始する。
   以前は再生位置を0x0000に固定していたため、リング先頭の無音約1.38秒を
	   先に再生して映像が音声より先行していた。BODY-arm audioを同じ位置へ
   先行配置し、PCM_STもSYNC_LEADへ合わせることでframe0と音声の先頭を揃える。
   SYNC_MIN(リード下限)を割ると書込を play+SYNC_LEAD へジャンプ=re-sync(古い音をまたぐ乱れ)。
   重いシーン転換クラスタで映像が数コマ遅れリードが一瞬凹むが、O_LEAD計測で底≈0x5BB(machi_op
   F1056)と実測。起動用先行チャンクを消費する間も不要なre-syncを起こさないよう、
   下限は0(追いついた位置での人工的な再アンカーを禁止)に置く。 */
.equ SYNC_LEAD, 0x3000
.equ SYNC_MIN,  0x0000
.equ SYNC_MAX,  0x6800

.equ HEADER_SECTORS,  1
/* frames/tcols/trows/cells/pool/base/prebuf/routing/mode は HEADER.DAT の
   v17ヘッダから起動時に読む(h_* 変数)。焼き込み定数の手動更新は廃止。 */

.equ CMD_STREAM, 0x50
.equ CMD_SWAP,   0x51
.equ STAT_BOOT_STAGE, 0x8001		/* palette/Dic stage ready for one-time Main copy */
.equ STAT_READY, 0x8003
.equ STAT_END,   0x8004			/* 全フレーム再生完了(MDは15秒待って CMD_STREAM 再送) */

.macro BIOSCALL code
	move.w	#\code, d0
	jsr	CDBIOS
.endm

.text

sp_header:
	.ascii	"MAIN       "
	.byte	0
	.word	0x0100
	.word	0
	.long	0
	/* BIOS module ownership covers only this resident base image. */
	.long	sp_end-sp_header
	.long	sp_jmptbl-sp_header
	.long	0
sp_jmptbl:
	.word	sp_init-sp_jmptbl
	.word	sp_main-sp_jmptbl
	.word	sp_int2-sp_jmptbl
	.word	sp_user-sp_jmptbl
	.word	0

.global sp_init
sp_init:
	move.w	#0x2700, sr
	andi.w	#0xFFFA, (MEMMODE).l
	move.w	#0, (COMSTAT0).l
	move.w	#0, (COMSTAT1).l
	rts

.global sp_main
sp_main:
command_loop:
	tst.w	(COMCMD0).l
	bne	1f
	bra	command_loop
1:
	cmp.w	#CMD_STREAM, (COMCMD0).l
	beq	do_stream
	move.w	(COMCMD0).l, (COMSTAT0).l
2:
	tst.w	(COMCMD0).l
	bne	2b
	move.w	#0, (COMSTAT0).l
	bra	sp_main

do_stream:
	movea.l	#SP_STACK, sp
	move.w	#CMD_STREAM, (COMSTAT0).l
	/* BIOSのCDCセクタ管理は割り込み駆動。IENを立てsrを下げないと、連続読みで
	   ポーリングの隙間にセクタが化け/欠ける(実証: XOR不一致)。元プレイヤと同じ設定。 */
	ori.b	#0x04, (SUB_GA_BASE+0x37).l	/* HOCK: enable CDD communication */
	ori.b	#0x3C, (SUB_GA_BASE+0x33).l	/* IEN: enable INT2-5 (timer/CDD/CDC) */
	move.w	#0x2000, sr			/* enable ints BEFORE the BIOS calls */
	andi.b	#0xFA, (MEMMODE+1).l
	lea	drv_init_tracklist, a0
	BIOSCALL BIOS_DRV_INIT
1:
	BIOSCALL BIOS_CDB_STAT
	andi.b	#0xF0, (CDB_STAT).w
	bne	1b
	bsr	init_iso9660
	lea	file_header, a0
	bsr	find_file		/* d0=LBA, d1=sector count */
	move.l	d0, header_lba
	move.l	d1, header_total
	lea	file_body, a0
	bsr	find_file
	move.l	d0, body_lba
	move.l	d1, body_total
	bset	#2, (MEMMODE+1).l
stream_start:
	/* Every replay reloads the immutable startup file, builds frame 0 while the
	   timed reader is idle, then starts BODY.DAT from its own ISO extent. */
	clr.w	slip_count
	clr.w	desync_count
	clr.w	(COMSTAT1).l
	clr.w	(COMSTAT2).l
	clr.w	drain_frame
.ifdef INCLUDE_WORDBUF_RING
	clr.w	word_pending_count
.endif
	bsr	init_pcm
	clr.l	prev_msf			/* HEADER first sector establishes the disc MSF base */
	clr.l	base_msf
	move.l	header_lba, d0
	move.l	header_total, d1
	bsr	issue_file_readn		/* complete startup file */
	/* ヘッダ1secをSTAGEへ取り込み、マジック "TTRC" を検証(MOVIE.md) */
	moveq	#HEADER_SECTORS, d0
	lea	PAD_SCR, a0
	bsr	drain_lin
	cmpi.l	#0x54545243, (PAD_SCR).l	/* "TTRC" */
	bne	bad_header_magic
	cmpi.w	#ROUTING_VERSION, (PAD_SCR+4).l
	beq	1f
	move.w	#0xBAD7, (COMSTAT1).l		/* packed-routing format required */
	bra	bad_header
bad_header_magic:
	move.w	#0xBAD0, (COMSTAT1).l		/* 不一致: 診断マーカーを出して停止 */
bad_header:
	bra	bad_header
1:
	/* ヘッダ解析(>4sHHHHHHHHH + >LLLL + mode@38)。焼き込み定数を廃し実行時に読む */
.ifdef PLAYER_SPECIALIZED
	/* The generated constants came from these exact first 64 bytes.  A different
	   profile has a different signature at offset 192 and must stop before any
	   immediate geometry/timing value can reach the hot path. */
	cmpi.l	#PC_SIGNATURE, (PAD_SCR+192).l
	beq.s	1f
	move.w	#0xBAD1, (COMSTAT1).l
	bra	bad_header
1:
	clr.w	sec_acc
	clr.w	lead
.else
	lea	PAD_SCR, a0
	moveq	#0, d1
	move.w	6(a0), d1
	beq.s	bad_header
	cmpi.w	#ROUTING_MAX_FRAMES, d1		/* one-byte table: 16KB = 16384 frames */
	bhi.s	bad_header
	move.w	d1, h_frames
	addi.w	#ROUTING_SECTOR_BYTES-1, d1
	lsr.w	#ROUTING_SECTOR_SHIFT_A, d1
	lsr.w	#ROUTING_SECTOR_SHIFT_B, d1	/* exact routing_sec = ceil(frames/2048) */
	cmp.l	26(a0), d1			/* long compare also rejects a nonzero high half */
	bne.s	bad_header
	move.w	d1, h_routing_sec
	move.w	14(a0), h_pool			/* tile pool slots; validates run-descriptor bounds */
	move.w	12(a0), d0			/* cells */
	move.w	d0, h_cells
	addq.w	#7, d0
	lsr.w	#3, d0
	move.w	d0, h_bmbytes			/* ceil(cells/8) */
	move.l	30(a0), d0
	move.w	d0, h_prebuf_sec
	move.l	22(a0), h_prebuf_pat
	move.l	40(a0), d0			/* v17: BODY-arm frame0 control sectors @offset40 */
	tst.w	d0
	beq	bad_header
	move.w	d0, h_f0_ctrl_sec
	move.l	44(a0), d0			/* v17: BODY-arm frame0 pattern sectors @offset44 */
	tst.w	d0
	beq	bad_header
	move.w	d0, h_f0_pat_sec
	move.l	48(a0), d0			/* v13: boot-stage sectors @offset48 */
	cmpi.w	#12, d0				/* v13 boot-stage upper bound: 24KB=12 sectors */
	bls	1f
	moveq	#12, d0
1:
	move.w	d0, h_paltab_sec
	/* Adapt both mid-expand and wave-writer polls to nominal fps.  Pattern
	   supply independently selects the cold-run parser at every cadence. */
	move.w	#0x03FF, d1
	move.w	#0x01FF, d2
	move.w	56(a0), d0			/* nominal fps; zero safely selects dense polling */
	cmp.w	#24, d0
	bhs	pm_set
	moveq	#63, d1
	move.w	#0x00FF, d2
pm_set:
	move.w	d1, pump_mask
	move.w	d2, wave_pump_mask
	tst.w	d0
	beq	bad_header			/* v9 rate modulus must be nonzero */
	move.w	54(a0), d0
	move.w	d0, h_audio_bytes
	move.w	58(a0), d1			/* v9: RF5C164 frequency delta for fixed chunks */
	tst.w	d1
	beq	bad_header
	move.w	d1, h_audio_fd
	move.w	62(a0), h_features		/* v17 optional stream features */
	btst	#2, h_features+1
	bne	bad_header			/* removed audio-codec flag is reserved in v17 */
	move.w	h_features, d1
	andi.w	#0x0010, d1
	beq.s	1f
	btst	#FEATURE_PATTERN_SUPPLY_BIT, h_features+1
	beq	bad_header			/* list controls require authoritative run suffixes */
1:
	btst	#FEATURE_PATTERN_SUPPLY_BIT, 63(a0)
	bne	bad_header			/* supply needs generated preload counts/addresses */
	move.w	d0, d1
	btst	#0, d1				/* two decoded samples per packed byte */
	bne	bad_header
	lsr.w	#1, d1
	addq.w	#4, d1				/* predictor.w + index.b + reserved.b */
	move.w	d1, h_audio_control_bytes
	/* Feature bit 1 selects the exact fixed-N NTSC display cadence:
	   75 * N * 1001/60000 = 1001*N/800 sectors/frame.  The unreduced
	   runtime fraction produces the same accumulator sequence as the packer's
	   reduced N2=1001/400 or N4=1001/200 form. Feature-clear 24fps keeps
	   75/fps delivery pacing. */
	move.w	56(a0), d0			/* nominal fps */
	move.w	d0, d2				/* legacy modulus = nominal fps */
	move.w	#75, d1				/* precompute 75/fps quotient+remainder once */
	btst	#FEATURE_FIXED_N_BIT, 63(a0)
	beq	2f
	move.w	52(a0), d1			/* authoritative fixed VBlank interval N */
	tst.w	d1
	beq	bad_header
	cmpi.w	#4, d1				/* current routing/stopwatch contract supports N1..N4 */
	bhi	bad_header
	mulu.w	#1001, d1
	move.w	#800, d2
2:
	move.w	d2, sec_mod
	divu.w	d2, d1
	move.w	d1, sec_base
	swap	d1
	move.w	d1, sec_rem
	/* Controls carry future chunks, so no live audio write is skipped. */
	move.w	60(a0), h_audio_pre_sec
	beq	bad_header
	move.w	h_audio_pre_sec, d0
	add.w	h_f0_ctrl_sec, d0
	add.w	h_f0_pat_sec, d0
	move.w	d0, h_body_arm_sec
	clr.w	sec_acc
	clr.w	lead
.endif
	/* MDへヘッダ写しを渡す(frame0と同じバンクに書く=swap後にMDが読める) */
	lea	(O_HDR).l, a1
	moveq	#32-1, d1			/* 64B */
1:
	move.w	(a0)+, (a1)+
	dbra	d1, 1b
	/* The boot stage and DicBuf are handed to Main before frame 0 exists. Main
	   copies them to their persistent Main-RAM/VRAM homes and returns this bank,
	   allowing the same front-of-bank bytes to become O_LOADS and WordBuf. */
	.ifdef PLAYER_SPECIALIZED
	moveq	#PC_PALTAB_SEC, d0
	.else
	move.w	h_paltab_sec, d0
	beq	1f
	.endif
	lea	(O_PALTAB_STAGE).l, a0
	bsr	drain_lin_staged		/* CDC_TRN直行を避けSTAGE経由(スリップ防止) */
1:
.ifdef INCLUDE_PATTERN_SUPPLY
.if PC_DIC_SECTORS > 0
	moveq	#PC_DIC_SECTORS, d0
	lea	DIC_STAGE, a0
	bsr	drain_lin_staged
.endif
.endif
	/* This handoff is an intentional HEADER read boundary. Stop the finite
	   boot read before Main owns the bank; no arriving sector is allowed to
	   turn the copy interval into an unexpected slip. */
	BIOSCALL BIOS_CDC_STOP
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.w	#STAT_BOOT_STAGE, (COMSTAT0).l
1:
	tst.w	(COMCMD1).l
	beq.s	1b
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	clr.w	(COMSTAT0).l
	/* Restart at the first unread HEADER sector. reseek_readn deliberately
	   preserves the original file anchor used by exact MSF recovery. */
	.ifdef PLAYER_SPECIALIZED
	moveq	#HEADER_SECTORS+PC_PALTAB_SEC+PC_DIC_SECTORS, d0
	.else
	moveq	#HEADER_SECTORS, d0
	add.w	h_paltab_sec, d0
	.endif
	add.l	header_lba, d0
	move.l	stream_remaining, d1
	bsr	reseek_readn

	/* The five-sector image holds the unchanged 8,800-byte ADPCM tables,
	   followed by the checked boot extension in existing sector padding.
	   Keep the qualified 88-byte ADPCM copy byte-for-byte identical.  A route
	   longer than 8 KiB can overwrite the staged second entry, so only that
	   uncommon build copies the complete extension before routing is loaded. */
	moveq	#ADPCM_TABLE_SECTORS, d0
	lea	ROUTING_TMP, a0
	bsr	drain_lin_staged
	lea	SP_EXTENSION_LOAD_BASE, a0
	lea	SP_EXTENSION_EXEC_BASE, a1
.ifdef ROUTING_EXTENSION_IN_STAGE
	move.w	#ADPCM_BOOT_COPY_LONGS-1, d0
.else
	move.w	#SP_EXTENSION_LONGS-1, d0
.endif
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b
	lea	ADPCM_DELTAS, a2
	jsr	ADPCM_BOOT_COPY
	/* Wr0 is the physical frame-0 bank and Wr1 is the other bank. Their
	   generated starts and sector-rounded capacities differ. Two toggles
	   restore the frame-0 bank phase. */
.ifdef INCLUDE_PATTERN_SUPPLY
.if PC_WR0_SECTORS > 0
	moveq	#PC_WR0_SECTORS, d0
	lea	WORD_BUF0, a0
	bsr	drain_lin_staged
.endif
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
.if PC_WR1_SECTORS > 0
	moveq	#PC_WR1_SECTORS, d0
	lea	WORD_BUF1, a0
	bsr	drain_lin_staged
.endif
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
.endif
	/* WordBuf boot contents are the first ring turn. The timed writer starts
	   immediately after them and normalizes an exactly-full preload to base. */
.ifdef INCLUDE_WORDBUF_RING
	move.l	#WORD_BUF0+(PC_WR0_PATTERNS*32), d0
	cmpi.l	#WORD_BUF0_END, d0
	blo.s	1f
	move.l	#WORD_BUF0, d0
1:
	move.l	d0, word_write_ptr0
	move.l	#WORD_BUF1+(PC_WR1_PATTERNS*32), d0
	cmpi.l	#WORD_BUF1_END, d0
	blo.s	1f
	move.l	#WORD_BUF1, d0
1:
	move.l	d0, word_write_ptr1
	move.w	#PC_WR0_PATTERNS, word_level0
	move.w	#PC_WR1_PATTERNS, word_level1
.endif
	/* HEADER ends with the static routing table and frame-1 Prg prebuffer. */
	moveq	#0, d0
	PC_MOVE_W h_routing_sec, PC_ROUTING_SEC, d0
	lea	ROUTING_TMP, a0
	bsr	drain_lin_staged
	/* prebuffer(PREBUF1=frame1満タン) → STAGE経由でリング下部(RING_BASE)へ */
	move.l	#RING_BASE, ring_tail
	PC_MOVE_W h_prebuf_sec, PC_PREBUF_SEC, d7
	tst.w	d7
	beq	pb_done
pb_lp:
	movem.l	d7, -(sp)
	lea	PAD_SCR, a0
	bsr	drain1
	movea.l	ring_tail, a1
	bsr	stage_copy
	movem.l	(sp)+, d7
	movea.l	ring_tail, a0
	lea	0x800(a0), a0
	move.l	a0, ring_tail
	subq.w	#1, d7
	move.w	d7, (COMSTAT1).l		/* boot UI: remaining PrgBuf preload sectors */
	bne	pb_lp
pb_done:
	/* HEADER.DAT is exhausted, so a boot-only copy cannot delay its continuous
	   drain. Validate every packed route and duplicate the sector-sized routing
	   reservation into both physical 1M Word-RAM banks. This boot-only work runs
	   from the HEADER-preloaded extension, leaving resident space for Q. */
	lea	ROUTING, a1
	PC_MOVE_W h_frames, PC_FRAMES, d7
	move.w	#ROUTING_COPY_LONGS, d5
	PC_MOVE_L h_prebuf_pat, PC_PREBUF_PAT, d6
	lea	ring_head, a4
	lea	drain_k, a5
.ifdef ROUTING_EXTENSION_IN_STAGE
	jsr	(SP_EXTENSION_LOAD_BASE+ADPCM_BOOT_COPY_BYTES).l
.else
	jsr	(SP_EXTENSION_EXEC_BASE+ADPCM_BOOT_COPY_BYTES).l
.endif
	tst.w	d0
	bne	bad_header

	/* BODY begins with an explicit untimed arm. Read only that finite prefix so
	   no timed sector can arrive while frame-0 patterns still overlap the ring
	   tail/APPLY scratch. HEADER and BODY ISO extents are independent. */
	moveq	#0, d1
	PC_MOVE_W h_body_arm_sec, PC_BODY_ARM_SEC, d1
	move.l	body_total, d0
	cmp.l	d1, d0
	blo	bad_header
	clr.l	prev_msf
	clr.l	base_msf
	move.l	body_lba, d0
	bsr	issue_file_readn

	/* The first arm region contains one decoded PCM chunk per sector. Live
	   controls keep carrying future chunks, preserving source sample order. */
	PC_MOVE_W h_audio_pre_sec, PC_AUDIO_PRELOAD_SEC, d7
arm_audio_lp:
	movem.l	d7, -(sp)
	lea	PAD_SCR, a0
	bsr	drain1
	lea	PAD_SCR, a0
	bsr	write_wave_chunk
	movem.l	(sp)+, d7
	subq.w	#1, d7
	bne	arm_audio_lp

	/* Frame 0 follows in the same BODY arm. It remains an untimed exact
	   construction and never consumes the timed Prg ring. */
	moveq	#0, d0
	PC_MOVE_W h_f0_ctrl_sec, PC_F0_CTRL_SEC, d0
	lea	CTRL_SCR, a0
	bsr	drain_lin_staged
	move.l	#F0PAT_TMP, f0_pat_addr
	moveq	#0, d0
	PC_MOVE_W h_f0_pat_sec, PC_F0_PAT_SEC, d0
	movea.l	f0_pat_addr, a0
	bsr	drain_lin_staged
	BIOSCALL BIOS_CDC_STOP

	/* The extension prepared the steady-state queues and exact ring tail.
	   BODY-arm storage is complete, so expand frame 0 with no active CD read. */
	bsr	expand_frame
	clr.w	f0_expand

	/* Initialize the logical timed state while the CD remains stopped.  The
	   frame-0 bank must reach Main before any timed BODY sector can arrive. */
.ifdef DEBUG_PRGBUF_Q
	PC_MOVE_W h_prebuf_pat+2, PC_PREBUF_PAT, d0
	move.w	d0, ring_level
.endif
	move.w	#1, drain_frame
	move.l	#RING_BASE, ring_head

frame0_handoff:
	/* One CMD_STREAM command spans startup. Hand frame 0 to Main with the
	   suffix still stopped; Main shows F=FFFF, builds and flips F=0000, then
	   clears CMD_STREAM to launch the first timed BODY read. */
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
.ifdef INCLUDE_WORDBUF_RING
	move.w	#1, word_owned_bank		/* Main owns frame-0 bank; Sub owns Wr1 */
.endif
	move.w	#STAT_READY, (COMSTAT0).l
frame0_ready_wait:
	tst.w	(COMCMD0).l
	bne.s	frame0_ready_wait

timed_suffix_start:
	/* The frame-0 flip has happened. Start the one continuous timed read now.
	   ROM_READN has a startup interval before its first 75 Hz sector. Keep PCM
	   stopped through that interval, then start it immediately after the first
	   frame-1 control sector has arrived. The rest of frame 1's physical slot
	   supplies the normal frame-0 audio/display interval before Main proceeds. */
.ifdef PLAYER_SPECIALIZED
.if PC_FRAMES < 2
	bra	timed_suffix_armed
.endif
.else
	cmpi.w	#2, h_frames
	blo	timed_suffix_armed
.endif
.ifndef PLAYER_SPECIALIZED
	tst.l	body_total
	beq	timed_suffix_armed
.endif
	moveq	#0, d2
	PC_MOVE_W h_body_arm_sec, PC_BODY_ARM_SEC, d2
	move.l	body_lba, d0
	add.l	d2, d0
	move.l	body_total, d1
	sub.l	d2, d1
	beq	timed_suffix_armed
	clr.l	prev_msf
	clr.l	base_msf
	bsr	issue_file_readn
arm_frame1:
	bsr	pump1_core
	tst.w	pcm_running
	bne.s	1f
	/* The first routed sector is frame 1 control. drain_k is nonzero while
	   its physical slot remains open; a one-sector slot instead advances
	   drain_frame directly. Both cases prove that ROM_READN is flowing. */
	tst.w	drain_k
	bne.s	2f
	cmpi.w	#2, drain_frame
	blo.s	1f
2:
	bsr	pcm_on
1:
	cmpi.w	#2, drain_frame
	blo	arm_frame1
	bra.s	startup_ready
timed_suffix_armed:
	/* A one-frame/empty suffix has no first timed sector to anchor PCM. */
	bsr	pcm_on
startup_ready:
	/* Release Main only after the complete frame-1 physical slot is armed.
	   PCM has already run through the slot remainder, so frame 1 reaches the
	   next VBlank at the ordinary source-audio position instead of inheriting
	   ROM_READN's startup delay. */
	move.w	#0, (COMSTAT0).l
.equ ISO_HOLD_F0, 0			/* ISO診断: frame0 表示直後に静止(frame0単体の健全性確認) */
.if ISO_HOLD_F0
f0h1:
	bsr	dump_pats			/* 毎周 PREBUF1[0..] を O_LOADS へ(pumpしない=0xD000 pristine維持) */
f0hw:
	cmp.w	#CMD_SWAP, (COMCMD0).l
	bne	f0hw
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
.ifdef INCLUDE_WORDBUF_RING
	eori.w	#1, word_owned_bank
.endif
	move.w	#STAT_READY, (COMSTAT0).l
f0h2:
	tst.w	(COMCMD0).l
	bne	f0h2
	move.w	#0, (COMSTAT0).l
	bra	f0h1
.endif
.ifndef ISO_HOLD_N
.equ ISO_HOLD_N, 0			/* ISO診断: frame N を表示した状態で静止(0=無効) */
.endif
.equ ISO_HOLD_DUMP, 0			/* 0=クリーン静止(全画面=実フレームN) 1=内部状態ダンプ */
stream_loop:
	move.w	frame_idx, d0			/* 全フレーム処理済み=映画終端 */
	PC_CMP_W h_frames, PC_FRAMES, d0
	bhs	movie_end
	bsr	process_frame
3:
	cmp.w	#CMD_SWAP, (COMCMD0).l
	beq.s	5f				/* deadline first: do not pump once Main is waiting */
	bsr	pump_poll_core			/* MD待ち中だけCDを吸い上げ(溢れ防止) */
	bra	3b
5:
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
.ifdef INCLUDE_WORDBUF_RING
	eori.w	#1, word_owned_bank
.endif
	move.w	#STAT_READY, (COMSTAT0).l
.ifdef INCLUDE_WORDBUF_RING
	/* Let Main begin on the handed-off bank while Sub commits any Word sectors
	   accepted before the swap into the newly owned parity bank. */
	bsr	flush_word_pending
.endif
4:
	tst.w	(COMCMD0).l
	beq.s	5f				/* let Main and the next frame proceed immediately */
	bsr	pump_poll_core
	bra	4b
5:
	move.w	#0, (COMSTAT0).l
.if ISO_HOLD_N
	cmp.w	#ISO_HOLD_N+1, frame_idx	/* frame N 処理済み=表示中 */
	bne	stream_loop
.if ISO_HOLD_DUMP
	/* ISO診断: ring_head(現pop位置)から576パターンをダンプした擬似フレームを1回出して静止 */
	bsr	dump_ring_head
1:
	cmp.w	#CMD_SWAP, (COMCMD0).l
	bne	1b
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.w	#STAT_READY, (COMSTAT0).l
2:
	tst.w	(COMCMD0).l
	bne	2b
	move.w	#0, (COMSTAT0).l
hold_n:
	bra	hold_n
.else
	/* クリーン静止: frame N is already displayed after the completed handshake
	   above. Stop the Sub immediately; no synthetic zero-update swap is needed. */
hold_n:
	bra	hold_n
.endif

.if ISO_HOLD_DUMP
dump_ring_head:
	/* ISO診断: 内部状態5ロング値を各32bit=32タイル(白=1,黒=0)で表示。
	   loadsはラン形式: slot 0..159 連番 = 先頭に1ランのヘッダを置く。 */
	movem.l	d0-d7/a0-a6, -(sp)
	lea	dsv_vals, a3
	moveq	#0, d0
	move.w	frame_idx, d0
	move.l	d0, (a3)			/* [0]=frame_idx(=desyncしたコマ) */
	moveq	#0, d0
	move.w	(CTRL_SCR+2).l, d0
	move.l	d0, 4(a3)			/* [1]=読んだ frame_seq(実測) */
	move.l	apply_cur, 8(a3)		/* [2]=apply_cur */
	moveq	#0, d0
	move.w	slip_count, d0
	move.l	d0, 12(a3)			/* [3]=slip_count(CDCスリップ=グリッチ検出数) */
	moveq	#0, d0
	move.w	drain_frame, d0
	swap	d0
	move.w	desync_count, d0
	move.l	d0, 16(a3)			/* [4]=drain_frame|desync_count */
	clr.w	(O_PALW).l			/* keep the active boot-loaded palette */
	/* O_LOADS: slot0=黒(0x0000), slot1=白(0xFFFF) */
	lea	(O_LOADS).l, a1
	move.w	#0, (a1)+			/* slot_start=0 */
	move.w	#2, (a1)+			/* count=2 */
	move.w	#16-1, d0
1:
	clr.w	(a1)+
	dbra	d0, 1b
	move.w	#16-1, d0
1:
	move.w	#0xFFFF, (a1)+
	dbra	d0, 1b
	/* The diagnostic uses the live list-form control reader. CTRL_SCR is
	   disposable while this build is frozen, unlike the removed O_UPDS area. */
	move.w	#0x8000+1120, (CTRL_SCR+4).l
	clr.w	(CTRL_SCR+6).l
	lea	(CTRL_SCR+8).l, a2
	moveq	#0, d6				/* cell c */
uh_lp:
	moveq	#0, d0
	move.w	d6, d0
	divu	#40, d0				/* lo=v, hi=b */
	move.w	d0, d1				/* v */
	swap	d0
	move.w	d0, d2				/* b */
	moveq	#1, d3				/* 既定 ent=1 (slot0=黒) */
	cmp.w	#5, d1
	bhs	uh_put
	cmp.w	#32, d2
	bhs	uh_put
	lsl.w	#2, d1				/* v*4 */
	move.l	(a3,d1.w), d4
	moveq	#31, d5
	sub.w	d2, d5				/* bit = 31-b */
	btst	d5, d4
	beq	uh_put
	moveq	#2, d3				/* 白 slot1, ent=2 */
uh_put:
	move.w	d6, (a2)+
	move.w	d3, (a2)+
	addq.w	#1, d6
	cmp.w	#1120, d6
	blo	uh_lp
	move.w	#2, (O_NLOAD).l
	movem.l	(sp)+, d0-d7/a0-a6
	rts
/* ISO診断: ring_head から 1120 パターンを VRAM slot 0.. へ生ロードし、cell c→slot c で
   そのまま並べて表示。PREBUF1 が正しくロードされていれば(scrambleでも)実タイル片が見える。
   全面ノイズなら 0xC000 のリング内容が壊れている。 */
dump_pats:
	movem.l	d0-d7/a0-a6, -(sp)
	clr.w	(O_PALW).l			/* keep the active boot-loaded palette */
	lea	(O_LOADS).l, a1
	move.w	#0, (a1)+			/* slot_start=0 */
	move.w	#1120, (a1)+			/* count=1120 */
	movea.l	#RING_BASE, a4			/* PREBUF1先頭(frame1 cold)を固定で見る */
	move.w	#1120*8-1, d0			/* 1120*32B = 8960 long */
1:
	move.l	(a4)+, (a1)+
	cmpa.l	#RING_END, a4
	blo	2f
	movea.l	#RING_BASE, a4
2:
	dbra	d0, 1b
	move.w	#0x8000+1120, (CTRL_SCR+4).l
	clr.w	(CTRL_SCR+6).l
	lea	(CTRL_SCR+8).l, a2
	moveq	#0, d6
3:
	move.w	d6, (a2)+			/* cell */
	move.w	d6, d0
	addq.w	#1, d0				/* ent = slot+base(=1), pal0 */
	move.w	d0, (a2)+
	addq.w	#1, d6
	cmp.w	#1120, d6
	blo	3b
	move.w	#1, (O_NLOAD).l
	movem.l	(sp)+, d0-d7/a0-a6
	rts
dsv_vals:
	.long	0,0,0,0,0
sec_count:
	.long	0
xor_acc:
	.long	0
.endif
.endif
	bra	stream_loop

/* 映画終端: 最終フレームのswap要求に応えて表示→STAT_ENDをMDへ→PCM停止→
   CMD_STREAM(再開)を待って stream_start へ(=15秒待ちはMD側が数える) */
movie_end:
1:
	cmp.w	#CMD_SWAP, (COMCMD0).l
	bne	1b
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.w	#STAT_END, (COMSTAT0).l
2:
	tst.w	(COMCMD0).l
	bne	2b
	move.w	#0, (COMSTAT0).l
	move.b	#0xFF, (PCM_ONOFF).l		/* 全chオフ(静音) */
3:
	cmp.w	#CMD_STREAM, (COMCMD0).l	/* MDの再開指示を待つ */
	bne	3b
	bra	stream_start

/* Start one finite ISO file read. d0=absolute LBA, d1=sector count.  The caller
   establishes base_msf/prev_msf first so the very first sector is verifiable.
   Callers need no registers preserved. */
issue_file_readn:
	lea	bios_packet, a5
	move.l	d0, read_lba
	move.l	d1, read_total
	move.l	d0, (a5)
	move.l	d1, 4(a5)
	move.l	#SUB_BANK_1M, 8(a5)
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	BIOSCALL BIOS_ROM_READN
	move.l	read_total, stream_remaining
	rts

/* 滑り回復用の再シーク: d0=絶対LBA, d1=残セクタ数 で CDC_STOP+ROM_READN 再発行。
   連続読みの原則は破るが、滑り(MSFギャップ)は稀なので、失われたセクタを読み直して
   ストリームを厳密に継続する(=品質無劣化の回復)。 */
reseek_readn:
	movem.l	d0-d7/a0-a6, -(sp)
	lea	bios_packet, a5
	move.l	d0, (a5)
	move.l	d1, 4(a5)
	move.l	#SUB_BANK_1M, 8(a5)
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	BIOSCALL BIOS_ROM_READN
	move.l	d1, stream_remaining
	movem.l	(sp)+, d0-d7/a0-a6
	rts

/* 1セクタを (a0) へ CDC_TRN。連続読みをドレイン。宛先a0はBIOS呼びで壊れるので保存・再ロード。 */
drain1:
	move.l	a0, dr_dest
	lea	bios_packet, a5
1:
	BIOSCALL BIOS_CDC_STAT
	bcs	1b
2:
	BIOSCALL BIOS_CDC_READ
	bcc	2b
	move.w	#20000, d6			/* TRN有限リトライ(固着防止)。重フレームのバス競合で
						   2000では尽きてセクタ滑り→desyncしていた。転送は本来数回で
						   成功するので、上限を大きくしても正常時のコストは増えない。 */
3:
	movea.l	dr_dest, a0			/* CDC_TRN直前に宛先を再ロード */
	lea	12(a5), a1
	BIOSCALL BIOS_CDC_TRN
	bcs	4f
	subq.w	#1, d6
	bne	3b
.ifdef DEBUG_SUB_POLL_GAP
	addq.b	#1, (slip_count+1).w		/* total S only; do not carry into K */
.else
	addq.w	#1, slip_count			/* 回復: このセクタは失われた */
.endif
	BIOSCALL BIOS_CDC_ACK
	movea.l	dr_dest, a0
	bra	drain1
4:
	BIOSCALL BIOS_CDC_ACK
	subq.l	#1, stream_remaining
	/* 滑り検出: セクタヘッダ(BCD分秒フレーム)の連番検査。飛び=slip_count++ */
	lea	bios_packet+12, a0
	moveq	#0, d1
	move.b	(a0)+, d0
	bsr	bcd2bin
	move.w	d0, d1
	mulu	#60, d1
	move.b	(a0)+, d0
	bsr	bcd2bin
	add.w	d0, d1
	mulu	#75, d1
	move.b	(a0)+, d0
	bsr	bcd2bin
	add.l	d0, d1
	move.l	prev_msf, d2
	bne	d1_check
	move.l	d1, base_msf			/* 初回セクタ: ファイル先頭MSFを基準に記録 */
	bra	d1_ok
d1_check:
	addq.l	#1, d2				/* 期待 = prev_msf+1 */
	cmp.l	d1, d2
	beq	d1_ok				/* 連番=OK */
	/* MSFギャップ=滑り: 失われたセクタ(prev_msf+1=d2)へ再シークして読み直す(厳密回復)。
	   apply は total_len 前置きの可変長ストリームで、payloadだけ「穴」を空けても control が
	   落ちると parse がズレて永久desync(F273フリーズ実測)。かつ再シークの CDC_STOP は CDC を
	   リセットして後続の連鎖滑りを抑える(全payload-skipにすると滑り数が 38→59 に増える実測)。
	   Absolute LBA = read_lba + (d2 - base_msf), remaining = read_total - offset. */
.ifdef DEBUG_SUB_POLL_GAP
	/* Diagnostic packing: low byte remains the total S count; high byte K
	   counts only MSF sequence gaps.  A TRN retry exhaustion increments only
	   the low byte at the earlier recovery site. */
	/* Increment the two packed byte counters independently so an S wrap
	   cannot carry into K. */
	addq.b	#1, (slip_count).w
	addq.b	#1, (slip_count+1).w
.else
	addq.w	#1, slip_count
.endif
	move.l	d2, d0
	sub.l	base_msf, d0			/* ファイル相対セクタ */
	move.l	read_total, d1
	sub.l	d0, d1				/* 残セクタ数 */
	add.l	read_lba, d0			/* absolute LBA */
	bsr	reseek_readn
	movea.l	dr_dest, a0			/* drain1再入用に宛先を復元 */
	bra	drain1				/* 再読み: CDCは今度 d2 を返す→連番に戻る */
d1_ok:
	move.l	d1, prev_msf
	rts

bcd2bin:
	move.w	d0, d2
	andi.w	#0x0F, d2
	lsr.w	#4, d0
	mulu	#10, d0
	add.w	d2, d0
	rts

/* d0=セクタ数, a0=先頭(線形)。d0 セクタを a0.. へドレイン。 */
drain_lin:
	movem.l	d0-d7/a0-a6, -(sp)
	move.w	d0, d7
	subq.w	#1, d7
dl_loop:
	movem.l	d7/a0, -(sp)
	bsr	drain1				/* (a0)へ1セクタ */
	movem.l	(sp)+, d7/a0
	lea	0x800(a0), a0
	dbra	d7, dl_loop
	movem.l	(sp)+, d0-d7/a0-a6
	rts

/* d0=セクタ数, a0=先頭(線形)。CDC_TRNをPRG直行させず STAGE(PAD_SCR=Word-RAM)経由で
   CPUコピー。AGENTS.md: CDC_TRN→PRG直行はリトライ中にセクタが滑る(frame0ヘッダの
   直読みで frame0 全面ノイズ化の実証)。boot のヘッダブロック読みはこの安全経路を使う。 */
drain_lin_staged:
	movem.l	d0-d7/a0-a6, -(sp)
	move.w	d0, d7
	subq.w	#1, d7
dls_loop:
	movem.l	d7/a0, -(sp)
	lea	PAD_SCR, a0
	bsr	drain1				/* CD→PAD_SCR(Word-RAM STAGE) */
	movem.l	(sp)+, d7/a0
	movem.l	d7/a0, -(sp)
	movea.l	a0, a1				/* stage_copy: PAD_SCR→a1(dest) */
	bsr	stage_copy
	movem.l	(sp)+, d7/a0
	lea	0x800(a0), a0
	dbra	d7, dls_loop
	movem.l	(sp)+, d0-d7/a0-a6
	rts

/* ---- ポンプ方式ドレイン ----
   CDは止まらず75セクタ/秒を吐き続けるので、取り込みをフレーム処理のテンポに縛ると
   MD側が重いフレームでCDC内部バッファが溢れセクタが失われる(以降ずっとズレる)。
   → セクタ単位カーソル(drain_frame, drain_k)で「届いたら即取り込む」。
   MD待ちループ中も pump_poll で吸い上げ、受け側(リング/apply)の余裕だけ確認する。 */

/* 1セクタを取り込む(ブロッキング)。CD→常にWord-RAM STAGE(実績ある経路)→
   BODYの control→payload→pad 順に apply/PRG ring/捨て場へ振り分け。
   (CDC_TRN→PRG直行はリトライ中にセクタが滑る事故が起きる: 実測+1/2フレーム) */
/* v4+ レートマッチpadding。各フレーム = fsec = max(n_pay+n_ctrl, ratedelta-lead) セクタ。
   ratedelta はfeature bit 1で固定N由来、それ以外は75/fpsの整数割当(累積器sec_acc)。
   固定N4は200コマに5×199+6×1、24fpsは75/24、固定N2は400コマに
   2×199+3×201。n_pay+n_ctrl を超える
   ぶん(pad)は読んで捨てる。fsec はコマ先頭(drain_k==0)で1回計算し cur_fsec に保持。
	   routingはコマ先頭でcacheし、drain1(BIOS呼びでd1等破壊)後はcacheから復元。 */
/* Non-preserving sector pump. Every caller either reloads its live state from
   memory or explicitly preserves the small subset it needs. */
pump1_core:
p1_top:
	moveq	#0, d0
	move.w	drain_frame, d0
	PC_CMP_W h_frames, PC_FRAMES, d0
	bhs	p1_ret				/* ストリーム終端: 読まずに戻る */
	tst.w	drain_k
	bne	p1_read				/* コマ途中: cur_fsec は計算済み */
	/* --- コマ先頭: v7+ routingを展開し cur_fsec を計算 --- */
	lea	ROUTING, a0
	moveq	#0, d2
	move.b	(a0,d0.w), d2			/* word prefix, total, n_ctrl */
	moveq	#ROUTING_CTRL_MASK, d1
	and.w	d2, d1
	move.w	d2, d3
	andi.w	#ROUTING_WORD_MASK, d3
	lsr.w	#ROUTING_WORD_SHIFT, d3
	btst	#2, d1				/* ctrl bit 2 extends Word prefix 3 -> 4 */
	beq.s	9f
	andi.w	#ROUTING_CTRL_COUNT_MASK, d1
	addq.w	#1, d3
9:
	move.w	d1, cur_n_ctrl
	move.w	d3, cur_n_word
	andi.w	#ROUTING_TOTAL_MASK, d2
	lsr.w	#ROUTING_TOTAL_SHIFT, d2
	move.w	d2, cur_total
	/* ratedelta = base + carry(acc+rem, mod). Numerator/modulus quotient and
	   remainder were computed once at header load, so this path needs no DIVU. */
	PC_MOVE_W sec_base, PC_SEC_BASE, d5	/* d5 = base quotient */
	move.w	sec_acc, d0
	PC_ADD_W sec_rem, PC_SEC_REM, d0
	PC_CMP_W sec_mod, PC_SEC_MOD, d0
	blo.s	1f
	PC_SUB_W sec_mod, PC_SEC_MOD, d0
	addq.w	#1, d5
1:
	move.w	d0, sec_acc			/* accumulator remainder */
	move.w	d5, d6				/* delta = ratedelta - lead(先行ぶん, 負可) */
	sub.w	lead, d6
	cmp.w	d6, d2				/* cur_fsec = max(total, delta) 符号付き */
	bge.s	1f				/* total >= delta → cur_fsec = total */
	move.w	d6, d2				/* else cur_fsec = delta */
1:
	move.w	d2, cur_fsec
	move.w	lead, d6			/* lead += cur_fsec - ratedelta (常に≥0) */
	add.w	d2, d6
	sub.w	d5, d6
	move.w	d6, lead
	tst.w	cur_fsec			/* fsec==0(total=0かつ先行中)= ディスク上0セクタ */
	bne.s	p1_read
	addq.w	#1, drain_frame			/* 前進のみ、read無し(データは先行配送済み) */
	clr.w	drain_k
	bra	p1_top
p1_read:
.ifdef INCLUDE_WORDBUF_RING
	/* A future frame's control and Word prefix may be drained before the bank
	   swap. word_accept_guard either proves a direct write or reserves one of
	   four Sub-PRG pending sectors, keeping the continuous CDC read moving. */
	move.w	drain_k, d3
	move.w	cur_n_ctrl, d1
	cmp.w	d1, d3
	blo.s	p1_drain
	add.w	cur_n_word, d1
	cmp.w	d1, d3
	bhs.s	p1_drain
	bsr	word_accept_guard
	tst.w	d0
	beq	p1_ret
p1_drain:
.endif
	lea	PAD_SCR, a0			/* STAGE = Word-RAM */
	bsr	drain1				/* 1セクタ取り込み(d1/d2破壊) */
	move.w	cur_n_ctrl, d1
	move.w	cur_total, d4			/* stage_copy preserves cached routing in memory */
	move.w	drain_k, d3
	cmp.w	d1, d3
	blo	p1_apply			/* k < n_ctrl: BODY control comes first */
.ifdef INCLUDE_WORDBUF_RING
	add.w	cur_n_word, d1
	cmp.w	d1, d3
	blo	p1_word				/* leading payload prefix -> parity WordBuf */
.endif
	cmp.w	d4, d3
	blo	p1_ring				/* n_ctrl <= k < total: payload */
	bra	p1_adv				/* k >= total: pad セクタ(捨て) */
.ifdef INCLUDE_WORDBUF_RING
p1_word:
	move.w	drain_frame, d0
	andi.w	#1, d0
	cmp.w	word_owned_bank, d0
	bne.s	p1_word_pending
	tst.w	d0
	bne.s	p1_word_direct1
	movea.l	word_write_ptr0, a1
	bsr	stage_copy
	movea.l	word_write_ptr0, a0
	lea	0x800(a0), a0
	cmpa.l	#WORD_BUF0_END, a0
	blo.s	2f
	movea.l	#WORD_BUF0, a0
2:
	move.l	a0, word_write_ptr0
	addi.w	#64, word_level0
	bra	p1_adv
p1_word_direct1:
	movea.l	word_write_ptr1, a1
	bsr	stage_copy
	movea.l	word_write_ptr1, a0
	lea	0x800(a0), a0
	cmpa.l	#WORD_BUF1_END, a0
	blo.s	2f
	movea.l	#WORD_BUF1, a0
2:
	move.l	a0, word_write_ptr1
	addi.w	#64, word_level1
	bra	p1_adv
p1_word_pending:
	move.w	word_pending_count, d0
	bne.s	1f
	movea.l	#WORD_PENDING0, a1
	move.w	drain_frame, word_pending_frame
	bra.s	4f
1:
	cmpi.w	#1, d0
	bne.s	2f
	movea.l	#WORD_PENDING1, a1
	bra.s	4f
2:
	cmpi.w	#2, d0
	bne.s	3f
	lea	word_pending2, a1
	bra.s	4f
3:
	movea.l	#WORD_PENDING3, a1
4:
	bsr	stage_copy
	addq.w	#1, word_pending_count
	bra	p1_adv
.endif
p1_ring:
	movea.l	ring_tail, a1
	bsr	stage_copy			/* STAGE→PRG 2048B CPUコピー */
	movea.l	ring_tail, a0
	lea	0x800(a0), a0
	cmpa.l	#RING_END, a0
	blo.s	1f
	movea.l	#RING_BASE, a0
1:
	move.l	a0, ring_tail
.ifdef DEBUG_PRGBUF_Q
	addi.w	#64, ring_level		/* one 2 KiB payload sector = 64 patterns */
.endif
.ifdef DEBUG
	/* Only a payload append can raise occupancy. Keep the exact sticky
	   high-water in 32-byte patterns in dedicated COMSTAT2; Main converts
	   it to J's ceil-KiB excess. Frame-0 boot staging never reaches this path. */
	move.l	a0, d0
	sub.l	ring_head, d0
	bpl.s	2f
	add.l	#RING_SIZE, d0
2:
	lsr.l	#5, d0				/* exact occupied pattern count */
	cmp.w	(COMSTAT2).l, d0
	bls.s	3f
	move.w	d0, (COMSTAT2).l
3:
.endif
	bra.s	p1_adv
p1_apply:
	movea.l	apply_tail, a1
	bsr	stage_copy
	movea.l	apply_tail, a0
	lea	0x800(a0), a0
	cmpa.l	#APPLY_END, a0
	blo.s	1f
	movea.l	#APPLY_BASE, a0
1:
	move.l	a0, apply_tail
p1_adv:
	addq.w	#1, drain_k
	move.w	drain_k, d3
	cmp.w	cur_fsec, d3			/* v4: fsec(=max(total,rate) レートマッチ)セクタで1コマ完了 */
	blo.s	p1_ret
	clr.w	drain_k
	addq.w	#1, drain_frame
p1_ret:
.ifdef DEBUG_SUB_POLL_GAP
	/* Exclude all time spent in CDC_STAT/READ/TRN, stage copy, and slip
	   recovery from the next outside-pump interval. */
	move.w	(GA_STOPWATCH_ABS_W).w, d0
	move.w	d0, (poll_last_tick).w
.endif
	rts

/* Copy the 2 KB CDC stage to PRG RAM. Six 48-byte MOVEM transfers per loop
   preserve the proven bus operation while minimizing loop/address overhead on
   this fixed 75 Hz path; one final 32-byte MOVEM completes the sector. */
stage_copy:
	lea	PAD_SCR, a0
copy_sector:
	move.w	#7-1, d0			/* 7 * 6 * 48 = 2016 bytes */
1:
	movem.l	(a0)+, d1-d7/a2-a6
	movem.l	d1-d7/a2-a6, (a1)
	movem.l	(a0)+, d1-d7/a2-a6
	movem.l	d1-d7/a2-a6, 48(a1)
	movem.l	(a0)+, d1-d7/a2-a6
	movem.l	d1-d7/a2-a6, 96(a1)
	movem.l	(a0)+, d1-d7/a2-a6
	movem.l	d1-d7/a2-a6, 144(a1)
	movem.l	(a0)+, d1-d7/a2-a6
	movem.l	d1-d7/a2-a6, 192(a1)
	movem.l	(a0)+, d1-d7/a2-a6
	movem.l	d1-d7/a2-a6, 240(a1)
	lea	288(a1), a1
	dbra	d0, 1b
	movem.l	(a0)+, d1-d7/a2		/* final 32 bytes */
	movem.l	d1-d7/a2, (a1)
	rts

/* ノンブロッキング: CDCにセクタが用意できていて、受け側に余裕があれば1セクタ取り込む。
   MD待ちループから毎回呼ぶ。 */
pump_poll:
	movem.l	d0-d7/a0-a6, -(sp)
	bsr	pump_poll_core
	movem.l	(sp)+, d0-d7/a0-a6
	rts

/* a4 is the local PrgBuf pop cursor during expansion. Publish completed pops
   before a refill poll; otherwise pump_poll sees the previous frame's full
   ring until ef_store and suppresses the only post-cold refill opportunity. */
pump_poll_after_pop:
	tst.w	f0_expand
	bne.s	1f
.ifdef DEBUG_PRGBUF_Q
	/* Pop accounting is updated by each Prg run, but compare only at the
	   existing refill boundary. This preserves the pre-refill minimum without
	   adding a compare to every descriptor in the Sub hot loop. */
.ifdef DEBUG_PRGMIN_DIRECT
	move.w	ring_level, (O_PRGMIN).l
.else
	move.w	ring_level, d0
	cmp.w	ring_frame_min, d0
	bge.s	2f
	move.w	d0, ring_frame_min
2:
.endif
.endif
	move.l	a4, ring_head
1:
	bra.s	pump_poll

pump_poll_core:
.ifdef DEBUG_SUB_POLL_GAP
	/* Time spent outside the CDC pump: from the end of the previous
	   pump/service call to this poll entry.  pump1_core refreshes the origin
	   again after a blocking transfer or recovery, so G does not mistake the
	   recovery itself for the delay that caused it. */
	move.w	(GA_STOPWATCH_ABS_W).w, d0
	sub.w	poll_last_tick, d0
	andi.w	#0x0FFF, d0
	cmp.w	poll_max_gap, d0
	bls.s	9f
	move.w	d0, (poll_max_gap).w
9:
.endif
	move.w	drain_frame, d0
	beq	pp_done				/* v2: frame0展開中は drain_frame=0。ここで pump すると
						   routing[0]=0 によりframe1の実セクタをpad扱いで捨て、
						   CD位置とdrain_k/frameが N セクタ desync → frame1が化ける。
						   streaming state(drain_frame>=1)確立まで pump しない。 */
	PC_CMP_W h_frames, PC_FRAMES, d0
	bcc	pp_done				/* ストリーム終端 */
	/* Guard only the destination of the next physical sector.  The old pair
	   of unconditional guards stopped control and padding whenever PrgBuf was
	   full (and stopped payload whenever APPLY was full), so the continuously
	   arriving CD sectors slipped even though their actual destination had
	   room.  ROUTING is valid in both physical Word-RAM banks. */
	lea	ROUTING, a0
	moveq	#0, d2
	move.b	0(a0,d0.w), d2
	moveq	#ROUTING_CTRL_MASK, d1
	and.w	d2, d1				/* packed n_ctrl + Word-4 escape */
.ifdef INCLUDE_WORDBUF_RING
	move.w	d2, d4
	andi.w	#ROUTING_WORD_MASK, d4
	lsr.w	#ROUTING_WORD_SHIFT, d4
	btst	#2, d1
	beq.s	9f
	andi.w	#ROUTING_CTRL_COUNT_MASK, d1
	addq.w	#1, d4
9:
.endif
	move.w	drain_k, d3
	cmp.w	d3, d1
	bhi.s	pp_apply_space			/* k < n_ctrl: control -> APPLY only */
.ifdef INCLUDE_WORDBUF_RING
	/* A Word payload can enter its owned bank directly or a reserved Sub-PRG
	   pending sector while waiting for the next physical bank swap. */
	add.w	d1, d4
	cmp.w	d4, d3
	bhs.s	pp_not_word
	bsr	word_accept_guard
	tst.w	d0
	beq	pp_done
	bra	pp_cdc
pp_not_word:
.endif
	andi.w	#ROUTING_TOTAL_MASK, d2
	lsr.w	#ROUTING_TOTAL_SHIFT, d2	/* total useful sectors */
	cmp.w	d3, d2
	bls.s	pp_cdc				/* k >= total: padding -> no buffer guard */
	/* Payload -> PrgBuf only. occupied=(tail-head) mod SIZE. */
	move.l	ring_tail, d0
	sub.l	ring_head, d0
	bpl.s	1f
	add.l	#RING_SIZE, d0
1:
	cmp.l	#RING_SIZE-0x1000, d0
	bcc.s	pp_done
	bra.s	pp_cdc
pp_apply_space:
	/* Control -> APPLY only. */
	move.l	apply_tail, d0
	sub.l	apply_cur, d0
	bpl.s	2f
	add.l	#APPLY_SIZE, d0
2:
	cmp.l	#APPLY_SIZE-0x1000, d0
.ifdef DEBUG_SUB_POLL_GAP
	bcc.s	pp_apply_blocked
.else
	bcc.s	pp_done
.endif
pp_cdc:
	/* CDCにセクタ準備できてる? (CDC_STAT: キャリー=未準備) */
	BIOSCALL BIOS_CDC_STAT
	bcs.s	pp_done
	bsr	pump1_core
.ifdef DEBUG_SUB_POLL_GAP
	bra.s	pp_done
pp_apply_blocked:
	/* pf_ctrl_wait's low byte is C. Its otherwise-unused high-byte sign bit
	   carries the sticky per-frame B marker without disturbing G updates. */
	tas	(pf_ctrl_wait).w
.endif
pp_done:
.ifdef DEBUG_SUB_POLL_GAP
	/* Start the next outside-pump interval only after all guard and CDC
	   polling work in this call has finished. */
	move.w	(GA_STOPWATCH_ABS_W).w, d0
	move.w	d0, (poll_last_tick).w
.endif
	rts

.ifdef INCLUDE_WORDBUF_RING
/* Return d0=1 iff the next Word sector has a bounded destination. Direct
   writes require the current parity bank. A not-yet-owned bank reserves up to
   four sectors without making those queued patterns logically resident. */
word_accept_guard:
	moveq	#0, d0
	move.w	drain_frame, d0
	cmp.w	frame_idx, d0
	bne.s	wag_no			/* never refill a bank after its frame began expanding */
	move.w	d0, d1
	andi.w	#1, d1
	tst.w	d1
	bne.s	1f
	move.w	word_level0, d2
	move.w	#WORD_BUF0_CAP, d3
	bra.s	2f
1:
	move.w	word_level1, d2
	move.w	#WORD_BUF1_CAP, d3
2:
	cmp.w	word_owned_bank, d1
	bne.s	wag_pending
	tst.w	word_pending_count
	bne.s	wag_no
	addi.w	#64, d2
	cmp.w	d3, d2
	bhi.s	wag_no
	moveq	#1, d0
	rts
wag_pending:
	move.w	word_pending_count, d4
	cmpi.w	#4, d4
	bhs.s	wag_no
	tst.w	d4
	beq.s	1f
	cmp.w	word_pending_frame, d0
	bne.s	wag_no
1:
	addq.w	#1, d4
	lsl.w	#6, d4
	add.w	d4, d2
	cmp.w	d3, d2
	bhi.s	wag_no
	moveq	#1, d0
	rts
wag_no:
	moveq	#0, d0
	rts

/* Commit pending sectors after the physical swap. COMSTAT0 is already READY,
   so Main can build the handed-off frame in parallel on the other bank. */
flush_word_pending:
	tst.w	word_pending_count
	beq.s	fwp_done
	movea.l	#WORD_PENDING0, a0
	bsr	flush_word_one
	cmpi.w	#2, word_pending_count
	blo.s	fwp_clear
	movea.l	#WORD_PENDING1, a0
	bsr	flush_word_one
	cmpi.w	#3, word_pending_count
	blo.s	fwp_clear
	lea	word_pending2, a0
	bsr	flush_word_one
	cmpi.w	#4, word_pending_count
	blo.s	fwp_clear
	movea.l	#WORD_PENDING3, a0
	bsr	flush_word_one
fwp_clear:
	clr.w	word_pending_count
fwp_done:
	rts

flush_word_one:
	move.w	word_pending_frame, d0
	andi.w	#1, d0
	bne.s	1f
	movea.l	word_write_ptr0, a1
	bsr	copy_sector
	movea.l	word_write_ptr0, a1
	lea	0x800(a1), a1
	cmpa.l	#WORD_BUF0_END, a1
	blo.s	2f
	movea.l	#WORD_BUF0, a1
2:
	move.l	a1, word_write_ptr0
	addi.w	#64, word_level0
	rts
1:
	movea.l	word_write_ptr1, a1
	bsr	copy_sector
	movea.l	word_write_ptr1, a1
	lea	0x800(a1), a1
	cmpa.l	#WORD_BUF1_END, a1
	blo.s	2f
	movea.l	#WORD_BUF1, a1
2:
	move.l	a1, word_write_ptr1
	addi.w	#64, word_level1
	rts
.endif

/* 1フレーム: BODY先頭側の control sector が揃うまでポンプ → control取り出し
   → expand → 音声。payload/pad はPrgBufを先行充填しながら後続処理と並走する。 */
process_frame:
.ifdef DEBUG
	clr.w	pf_ctrl_wait
	clr.w	pf_body_wait
.ifdef DEBUG_SUB_POLL_GAP
	move.w	(GA_STOPWATCH_ABS_W).w, d0
	move.w	d0, (poll_last_tick).w
	clr.w	(poll_max_gap).w
.endif
.ifdef DEBUG_PRGBUF_Q
.ifdef DEBUG_PRGMIN_DIRECT
	move.w	ring_level, (O_PRGMIN).l
.else
	move.w	ring_level, ring_frame_min
.endif
.endif
.endif
pf_pump:
	move.w	frame_idx, d0			/* pump1_core may trash d0; reload each pass */
	cmp.w	drain_frame, d0
	blo.s	pf_ready			/* drain_frame > frame_idx: full frame already drained */
	bhi.s	pf_body_blocked			/* BODY is still draining an older frame */
		/* Same frame: control must be complete. A ring stream also drains the
		   following Word prefix before expansion, so its capacity proof cannot
		   reuse patterns before Main has consumed the current bank. */
	lea	ROUTING, a0
	moveq	#0, d2
	move.b	(a0,d0.w), d2
	moveq	#ROUTING_CTRL_MASK, d1
	and.w	d2, d1				/* packed n_ctrl + Word-4 escape */
.ifdef INCLUDE_WORDBUF_RING
	andi.w	#ROUTING_WORD_MASK, d2
	lsr.w	#ROUTING_WORD_SHIFT, d2
	btst	#2, d1
	beq.s	9f
	andi.w	#ROUTING_CTRL_COUNT_MASK, d1
	addq.w	#1, d2
9:
	add.w	d2, d1				/* wait through the complete Word payload prefix */
.endif
	cmp.w	drain_k, d1
	bls.s	pf_ready
.ifdef DEBUG
	addq.w	#1, pf_ctrl_wait
	bra.s	pf_need_pump
.endif
pf_body_blocked:
.ifdef DEBUG
	addq.w	#1, pf_body_wait
.endif
pf_need_pump:
	bsr	pump1_core			/* non-preserving blocking sector pump */
	bra.s	pf_pump
pf_ready:
	addq.w	#1, frame_idx
	bsr	fetch_control			/* apply循環 → CTRL_SCR 線形化 */
	/* 同期チェック: control先頭の frame_seq(CTRL_SCR+2) が 期待値(frame_idx-1) と一致するか。
	   ズレ=desync(CDCセクタ落ち等)。破棄して前コマ維持(0更新)し、診断カウントを出す。
	   持続desyncは前コマ静止に化ける(=青赤崩壊より軽い)。 */
	move.w	(CTRL_SCR+2).l, d0		/* 実 frame_seq */
	move.w	frame_idx, d1
	subq.w	#1, d1				/* 期待 seq */
	cmp.w	d1, d0
	bne.s	pf_desync
	bsr	pump_poll_core
	bsr	expand_frame			/* CTRL_SCR → Word-RAM 出力 + 音声 */
	rts
pf_desync:
	addq.w	#1, desync_count
	move.w	desync_count, (COMSTAT1).l	/* 診断: desync回数 */
.equ DESYNC_DUMP, 0				/* 1: 初回desyncで[frame_idx,seq,apply_cur,apply_tail,drainF|cnt]を表示して静止 */
.if DESYNC_DUMP
	cmp.w	#1, desync_count
	bne	1f
	bsr	dump_ring_head
dsd_lp:
	cmp.w	#CMD_SWAP, (COMCMD0).l
	bne	dsd_lp
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.w	#STAT_READY, (COMSTAT0).l
dsd_w:
	tst.w	(COMCMD0).l
	bne	dsd_w
	move.w	#0, (COMSTAT0).l
	bra	dsd_lp
1:
.endif
	move.w	#0, (O_NLOAD).l			/* このコマは更新破棄=前コマ維持 */
	bsr	pump_poll_core
	rts

/* apply-buffer(PRG循環, apply_cur) から control block を CTRL_SCR(Word-RAM) へコピー(折返し線形化)。
   block先頭 >H total_len。apply_cur を total_len 進める。 */
fetch_control:
	/* The sole caller reloads every value it needs after this routine. */
	movea.l	apply_cur, a0
	move.w	(a0), d7			/* total_len */
	/* コピー: total_len バイトを a0(循環) → CTRL_SCR */
	lea	CTRL_SCR, a1
	move.w	d7, d6				/* 残バイト */
	/* first_part = min(total_len, APPLY_END - a0) */
	move.l	#APPLY_END, d0
	sub.l	a0, d0				/* d0 = APPLY_END - a0 (bytes) */
	cmp.w	d6, d0
	bcc.s	fc_nowrap			/* d0 >= 残 なら折返し無し */
	/* 折返し: first=d0 バイト, 残り d6-d0 */
	move.w	d0, d5				/* first bytes */
	sub.w	d5, d6				/* 残り */
	bsr	fc_copy_even
	movea.l	#APPLY_BASE, a0
fc_nowrap:
	/* 残 d6 バイトをコピー。d6=0でもfc_copy_evenはno-op。 */
	move.w	d6, d5
	bsr	fc_copy_even
fc_done:
	/* apply_cur += total_len, 折返し */
	movea.l	apply_cur, a0
	adda.w	d7, a0
	cmpa.l	#APPLY_END, a0
	blo.s	3f
	suba.l	#APPLY_SIZE, a0
3:
	move.l	a0, apply_cur
	rts					/* issue#15: 冗長movem削除(process_frameが退避済み) */

/* Copy d5 even bytes from a0 to a1. Control blocks and APPLY_SIZE are even, so
   both sides of a ring wrap remain aligned. Eight long moves per loop replace
   the old word-at-a-time copy; d3/d5 are scratch and the caller saves them. */
fc_copy_even:
	move.w	d5, d3
	lsr.w	#5, d3
	beq.s	2f
	subq.w	#1, d3
1:
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	dbra	d3, 1b
2:
	andi.w	#0x001F, d5
	move.w	d5, d3
	lsr.w	#2, d3
	beq.s	4f
	subq.w	#1, d3
3:
	move.l	(a0)+, (a1)+
	dbra	d3, 3b
4:
	btst	#1, d5
	beq.s	5f
	move.w	(a0)+, (a1)+
5:
	rts

/* CTRL_SCR(線形 control block) を Word-RAM へ展開。cold は ring pop。
   block = >H total_len >H frame_seq >H n_upd >H pal
           72 bitmap n_upd*(entry) h_audio_bytes audio [even pad]   (MOVIE.md 準拠)
   v3: pal = 区間番号+1(0=切替なし)。CRAM本体はboot時にMain-RAM表へ渡し済み(PALTAB)。
   loads はラン形式: [slot_start.w count.w pattern(count*32B)] の列。エンコーダが
   フレーム内coldを連番スロットに割当てるので、MDは1ランを1回の大DMAで転送できる。 */
expand_frame:
	lea	CTRL_SCR, a0
	addq.l	#4, a0				/* skip total_len(2) + frame_seq(2) */
	move.w	(a0)+, d5			/* bit15=list format, low15=n_upd */
	move.w	d5, d7			/* preserve format tag */
	andi.w	#SHADOW_UPDATE_COUNT_MASK, d5
	PC_MOVE_W h_bmbytes, PC_BMBYTES, d1	/* corrupt-count guard: never walk past this mode's cells */
	lsl.w	#3, d1
	cmp.w	d1, d5
	bls	1f
	move.w	d1, d5
1:
	move.w	(a0)+, d4			/* pal = 区間番号+1(0=切替なし) — MDはMain-RAM表を引く */
	move.w	d4, (O_PALW).l
ef_bm:
.equ ISO_DUMP_OFF, 0
	btst	#SHADOW_UPDATE_LIST_BIT, d7
	bne.s	ef_list_audio
	/* v17 retains the word-aligned 16-bit entry array after an odd-sized bitmap. The
	   specialized player folds that alignment into the immediate and adds no
	   runtime branch or code-size cost to the resident Sub image. */
.ifdef PLAYER_SPECIALIZED
	move.w	#((PC_BMBYTES+1)&0xFFFE), d0
	adda.w	d0, a0				/* entries */
.else
	move.w	h_bmbytes, d0
	adda.w	d0, a0
	btst	#0, d0
	beq.s	1f
	addq.l	#1, a0
1:
.endif
	/* Feed this frame's PCM before the variable-cost bitmap/cold expansion.
	   The control block is already linear and complete, so the audio position is
	   known now.  This only advances the time of the same writes; write_ptr and
	   the A/V sample position are unchanged.  In particular, a dense frame can
	   no longer postpone its own audio until after hundreds of tile updates. */
	movea.l	a0, a5				/* entries start */
	move.w	d5, d0				/* n_upd */
	add.w	d0, d0				/* two bytes per entry */
	adda.w	d0, a5				/* audio start */
	bra.s	ef_audio_positioned
ef_list_audio:
	movea.l	a0, a5				/* completed offset/entry pairs */
	move.w	d5, d0
	lsl.w	#2, d0				/* four bytes per list item */
	adda.w	d0, a5				/* audio start */
ef_audio_positioned:
	movea.l	a0, a6				/* preserve entries cursor across audio */
.ifdef DEBUG
	move.w	(GA_STOPWATCH).l, -(sp)
.endif
	movea.l	a5, a0
	bsr	decode_adpcm_chunk
.ifdef DEBUG
	move.w	(GA_STOPWATCH).l, d0
	sub.w	(sp)+, d0
	andi.w	#0x0FFF, d0
	move.w	d0, (O_AUDIOLEFT).l
.endif
	lea	PCM_DEC_BUF, a0
	bsr	write_wave_chunk
	movea.l	a6, a0
	lea	(O_LOADS).l, a1
	movea.l	ring_head, a4			/* pop ptr(PRG読み) */
	tst.w	f0_expand
	beq	ef_ring_count
	movea.l	f0_pat_addr, a4			/* frame0: popはboot専用PRG一時領域から(ring_headは0xD000維持) */
	moveq	#-1, d6				/* frame0 patterns are contiguous and never wrap */
	bra	ef_count_ready
ef_ring_count:
	move.l	#RING_END, d6
	sub.l	a4, d6
	lsr.l	#5, d6				/* patterns remaining before ring wrap */
ef_count_ready:
	moveq	#0, d4				/* n_load */
	/* v6+ streams append the packer's already-known cold slot runs after the
	   padded audio chunk.  At 24fps or above and n_upd<=1024 the entry walker has
	   exactly one CDC poll at the end, so the descriptor path preserves that
	   cadence while removing the duplicate entry scan and run reconstruction. */
.ifdef INCLUDE_PATTERN_SUPPLY
	/* v10 supply streams require the run suffix.  H40 frames above 1024
	   updates receive the legacy path's extra CDC service before copying runs;
	   the normal end poll below remains unchanged. */
	cmpi.w	#1024, d5
	bls	ef_runs_setup
	bsr	pump_poll
	bra	ef_runs_setup
.else
.ifdef INCLUDE_COLD_RUN_FASTPATH
.ifndef PLAYER_SPECIALIZED
	PC_MOVE_W h_features, PC_FEATURES, d0
	btst	#FEATURE_COLD_RUNS_BIT, d0
	beq	ef_entries
	cmpi.w	#0x03FF, pump_mask
	bne	ef_entries			/* lower rates retain their proven 64-entry cadence */
.endif
	cmpi.w	#1024, d5
	bhi	ef_entries			/* H40 >1024 needs the legacy intermediate poll */
.else
	bra	ef_entries
.endif
.endif
.ifdef INCLUDE_COLD_RUN_FASTPATH
ef_runs_setup:
	movea.l	a5, a0				/* audio start */
	PC_MOVE_W h_audio_control_bytes, PC_AUDIO_CONTROL_BYTES, d0
	adda.w	d0, a0				/* first byte after audio */
	move.l	a0, d0
	btst	#0, d0				/* align the absolute block address, not AUDIO alone */
	beq.s	1f				/* an odd H40 bitmap can start audio on an odd byte */
	addq.l	#1, a0
1:
	move.w	(a0)+, d7			/* n_runs */
	move.w	d5, d1				/* ordinary streams: runs/cold cannot exceed updates */
	PC_MOVE_W h_features, PC_FEATURES, d0
	btst	#FEATURE_VRAM_RAW_PREFETCH_BIT, d0
	beq.s	2f
	PC_MOVE_W h_cells, PC_CELLS, d1		/* prefetch runs have no corresponding name update */
2:
	cmp.w	d1, d7
	bls	1f
	move.w	d1, d7				/* corrupt-count clamp */
1:
	tst.w	d7
	beq	ef_runs_polled
	subq.w	#1, d7
ef_run:
	move.w	(a0)+, d2			/* Dic index high5 + zero-based slot low11 */
	move.w	(a0)+, d3			/* source2 + Dic index low3 + count low11 */
	move.w	d5, d1
	PC_MOVE_W h_features, PC_FEATURES, d0
	btst	#FEATURE_VRAM_RAW_PREFETCH_BIT, d0
	beq.s	2f
	PC_MOVE_W h_cells, PC_CELLS, d1
2:
	move.w	d3, d0
	andi.w	#0xC000, d0			/* preserve source for O_LOADS and the copy decision */
	andi.w	#0x07FF, d3
	sub.w	d4, d1				/* remaining cold count cannot exceed stream limit */
	cmp.w	d1, d3
	bls	1f
	move.w	d1, d3
1:
	andi.w	#0x07FF, d2			/* discard Dic index high bits for bounds proof */
	PC_MOVE_W h_pool, PC_POOL, d1
	sub.w	d2, d1				/* slots available from slot_start */
	bls	ef_run_next			/* corrupt slot outside the pool */
	cmp.w	d1, d3
	bls	1f
	move.w	d1, d3
1:
	tst.w	d3
	beq	ef_run_next
	move.w	-4(a0), (a1)+			/* preserve packed Dic index high bits */
	move.w	-2(a0), d1
	andi.w	#0xF800, d1			/* preserve source + Dic index low bits */
	or.w	d3, d1
	move.w	d1, (a1)+			/* indexed source/count; cached runs carry no inline bytes */
	add.w	d3, d4
.ifdef INCLUDE_WORDBUF_RING
	cmpi.w	#0x4000, d0
	bne.s	3f
	/* frame_idx already points one past the descriptor being expanded. Retire
	   that frame's parity now; Main completes the read before the bank returns. */
	move.w	frame_idx, d1
	subq.w	#1, d1
	andi.w	#1, d1
	bne.s	2f
	sub.w	d3, word_level0
	bra.s	3f
2:
	sub.w	d3, word_level1
3:
.endif
	tst.w	d0
	bne	ef_run_next			/* Wr/Dic: Main DMA reads the persistent preload directly */
.ifdef DEBUG_PRGBUF_Q
	/* Charge the complete Prg run before its bytes are copied.  Unlike the
	   modulo head/tail distance, this signed balance preserves an underflow
	   as negative debt until later payload sectors repay it. */
	sub.w	d3, ring_level
.endif
	subq.w	#1, d3
ef_run_pattern:
	/* Do not include postincrement base a4 in the MOVEM register list.  On
	   68000 its updated pointer value replaces one loaded long, turning the
	   same row of every 8x8 pattern into a horizontal dash. */
	movem.l	(a4)+, d0-d2/a2-a3/a5-a6	/* first 28 bytes */
	movem.l	d0-d2/a2-a3/a5-a6, (a1)
	move.l	(a4)+, 28(a1)			/* final 4 bytes without clobbering a4 */
	lea	32(a1), a1
	subq.w	#1, d6
	bne	1f
	movea.l	#RING_BASE, a4
	move.w	#RING_PATTERNS, d6
1:
	dbra	d3, ef_run_pattern
ef_run_next:
	/* The low-rate legacy walker polls every 64 entries. Pattern-supply
	   descriptors replaced that walk, but a single end-only poll leaves long
	   15fps frames with no CDC service after PrgBuf space starts opening.
	   Poll every four descriptors at low rate; d7 is already the persistent
	   descriptor countdown, so this adds no state or format field. */
.ifdef PLAYER_SPECIALIZED
.if PC_PUMP_MASK != 0x03FF
	move.w	d7, d0
	andi.w	#3, d0
	bne.s	1f
	bsr	pump_poll_after_pop
1:
.endif
.else
	cmpi.w	#0x03FF, pump_mask
	beq.s	1f
	move.w	d7, d0
	andi.w	#3, d0
	bne.s	1f
	bsr	pump_poll_after_pop
1:
.endif
	dbra	d7, ef_run
ef_runs_polled:
	tst.w	d5				/* legacy path polls once iff at least one entry exists */
	beq	ef_store
	bsr	pump_poll_after_pop
	bra	ef_store
.endif
.ifndef INCLUDE_PATTERN_SUPPLY
ef_entries:
	moveq	#0, d3				/* open run count (register-resident hot state) */
	movea.w	#-2, a6				/* a6=直前slot。先頭の+1が-1になる無効値で開始 */
	/* Main re-walks bitmap+entries from CTRL_SCR to update its cell shadow. The
	   Sub only needs cold entries in their existing stream order, so walking all
	   896 bitmap bits here was duplicate work. Iterate the n_upd entries directly. */
	move.w	d5, d7
	beq	ef_finalize
	subq.w	#1, d7
	move.w	d7, d1
	PC_AND_W pump_mask, PC_PUMP_MASK, d1	/* entries until the first poll minus one */
ef_entry:
	move.w	(a0)+, d2			/* entry */
	bpl	ef_entry_done			/* bit15 clear = reuse; Main consumes it directly */
ef_cold:
	andi.w	#0x07FF, d2			/* remove cold bit and keep slot+1 */
	subq.w	#1, d2				/* d2 = slot; d3 remains the run count */
	/* process_frame blocks until every sector assigned to this frame has been
	   drained, and pack_stream proves schedule under=0 for the complete stream.
	   Therefore this cold entry is resident; a per-cold ring occupancy check was
	   redundant hot-path work. Sector loss is recovered in drain1 before here. */
	addq.l	#1, a6				/* 直前slot+1 = 連結時に期待するslot */
	cmpa.w	d2, a6				/* 直前ランの続きか? (d2=slot) */
	beq	ef_cont
	tst.w	d3					/* 前のランを閉じる(countを書き戻す) */
	beq	1f
	move.w	d3, (a5)
1:
	move.w	d2, (a1)+			/* slot_start */
	movea.l	a1, a5				/* countワードの位置を覚える */
	addq.l	#2, a1				/* count is filled when the run closes */
	clr.w	d3
	movea.w	d2, a6				/* new run: remember its current last slot */
ef_cont:
	addq.w	#1, d3
	/* ring pop 32B: RING/O_LOADSとも4バイト整列・パターンはリング末端を跨がない
	   (RING_SIZEはセクタ倍数, パターンは32B整列)ので move.l×8 で一括コピー */
	move.l	(a4)+, (a1)+
	move.l	(a4)+, (a1)+
	move.l	(a4)+, (a1)+
	move.l	(a4)+, (a1)+
	move.l	(a4)+, (a1)+
	move.l	(a4)+, (a1)+
	move.l	(a4)+, (a1)+
	move.l	(a4)+, (a1)+
	subq.w	#1, d6
	bne	1f
	movea.l	#RING_BASE, a4
	move.w	#RING_PATTERNS, d6
1:
	addq.w	#1, d4
ef_entry_done:
	/* Keep the prior CDC cadence in units of useful entries: one end poll for
	   30fps, every 64 entries for <=20fps. Sparse frames finish sooner and need
	   no bitmap-time polls for cells the Sub no longer processes. */
	dbra	d1, 1f
	bsr	pump_poll_after_pop
	PC_MOVE_W pump_mask, PC_PUMP_MASK, d1
1:
	dbra	d7, ef_entry
ef_finalize:
	tst.w	d3					/* 最後のランを閉じる */
	beq	1f
	move.w	d3, (a5)
1:
.endif
ef_store:
.ifdef DEBUG_PRGBUF_Q
.ifndef INCLUDE_PATTERN_SUPPLY
	/* Canonical v17 streams use run descriptors above. Retain a final-balance
	   diagnostic for legacy builds without that suffix. */
	tst.w	f0_expand
	bne.s	8f
	sub.w	d4, ring_level
	move.w	ring_level, d0
	cmp.w	ring_frame_min, d0
	bge.s	8f
	move.w	d0, ring_frame_min
8:
.endif
.endif
	move.w	d4, (O_NLOAD).l
	move.w	slip_count, (O_SLIP).l	/* 滑り(=再シーク回復)回数をMDへ=グリッチマーカー */
	move.w	desync_count, (O_DSY).l	/* desync検知回数をMDへ(再シーク回復が効けば0のまま) */
	move.w	resync_count, (O_RESYNC).l	/* 計測: 音声re-sync回数をMDへ */
	move.w	cur_lead, (O_LEAD).l		/* 計測: 現コマの音声リードをMDへ */
.ifdef DEBUG
	move.w	pf_ctrl_wait, (O_CTRLWAIT).l
	move.w	pf_body_wait, (O_BODYWAIT).l
.ifdef DEBUG_SUB_POLL_GAP
	move.w	poll_max_gap, (O_PUMPGAP).l
.endif
.ifdef DEBUG_PRGBUF_Q
.ifndef DEBUG_PRGMIN_DIRECT
	move.w	ring_frame_min, (O_PRGMIN).l
.endif
.endif
.endif
	tst.w	f0_expand
	bne.s	1f
	move.l	a4, ring_head			/* frame0はring_head書き戻さない(0xD000維持=frame1がPREBUF1から) */
1:
	rts

swap_settle:
1:
	/* In 1M mode DMNA reads as 1 while the RET bank change is in progress and
	   clears when the new mapping is usable.  Wait for the hardware condition
	   instead of burning a fixed 0x400-iteration delay after every frame. */
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts

read_cd:
	movem.l	d0-d7/a0-a6, -(sp)
	lea	bios_packet, a5
	move.l	d0, (a5)
	move.l	d1, 4(a5)
	move.l	a0, 8(a5)
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	BIOSCALL BIOS_ROM_READN
wait_stat:
	BIOSCALL BIOS_CDC_STAT
	bcs.s	wait_stat
wait_read:
	BIOSCALL BIOS_CDC_READ
	bcc.s	wait_read
wait_transfer:
	movea.l	8(a5), a0
	lea	12(a5), a1
	BIOSCALL BIOS_CDC_TRN
	bcc.s	wait_transfer
	BIOSCALL BIOS_CDC_ACK
	addq.l	#1, (a5)
	addi.l	#0x0800, 8(a5)
	subq.l	#1, 4(a5)
	bne.s	wait_stat
	movem.l	(sp)+, d0-d7/a0-a6
	rts

init_iso9660:
	movem.l	d0-d7/a0-a6, -(sp)
	move.l	#0x10, d0
	move.l	#2, d1
	lea	ISO_BUF, a0
	bsr	read_cd
	lea	ISO_BUF, a0
	lea	156(a0), a1
	moveq	#0, d0
	move.b	6(a1), d0
	lsl.l	#8, d0
	move.b	7(a1), d0
	lsl.l	#8, d0
	move.b	8(a1), d0
	lsl.l	#8, d0
	move.b	9(a1), d0
	move.l	#0x20, d1
	lea	ISO_BUF, a0
	bsr	read_cd
	movem.l	(sp)+, d0-d7/a0-a6
	rts

find_file:
	movem.l	a1-a2/a6, -(sp)
	lea	ISO_BUF, a1
read_filename_start:
	movea.l	a0, a6
	move.b	(a6)+, d0
find_first_char:
	movea.l	a1, a2
	cmp.b	(a1)+, d0
	bne.s	find_first_char
check_chars:
	move.b	(a6)+, d0
	beq.s	get_info
	cmp.b	(a1)+, d0
	bne	read_filename_start
	bra	check_chars
get_info:
	sub.l	#33, a2
	moveq	#0, d0
	move.b	6(a2), d0
	lsl.l	#8, d0
	move.b	7(a2), d0
	lsl.l	#8, d0
	move.b	8(a2), d0
	lsl.l	#8, d0
	move.b	9(a2), d0
	/* Return file size as a rounded-up sector count in d1. */
	moveq	#0, d1
	move.b	14(a2), d1
	lsl.l	#8, d1
	move.b	15(a2), d1
	lsl.l	#8, d1
	move.b	16(a2), d1
	lsl.l	#8, d1
	move.b	17(a2), d1
	add.l	#2047, d1
	moveq	#11, d2
	lsr.l	d2, d1
	movem.l	(sp)+, a1-a2/a6
	rts

/* ---- RF5C164 PCM ---- */
init_pcm:
	movem.l	d0-d2/a0, -(sp)
	move.b	#0xFF, (PCM_ONOFF).l		/* keep playback stopped while the ring is armed */
	clr.w	pcm_running
	moveq	#0, d2
ip_loop:
	move.w	d2, d1
	andi.w	#0x0FFF, d1
	bne	1f
	move.w	d2, d0
	lsr.w	#8, d0
	lsr.w	#4, d0
	ori.b	#0x80, d0
	move.b	d0, (PCM_CTRL).l
1:
	lea	(PCM_WAVE).l, a0
	add.w	d1, d1
	adda.w	d1, a0
	move.b	#0x00, (a0)
	addq.w	#1, d2
	cmp.w	#WAVE_RING_END, d2
	blo	ip_loop
	move.b	#0x88, (PCM_CTRL).l
	move.b	#0xFF, (PCM_WAVE).l
	move.b	#0xC0, (PCM_CTRL).l
	move.b	#0xFF, (PCM_ENV).l
	nop
	nop
	move.b	#0xFF, (PCM_PAN).l
	nop
	nop
.ifdef PLAYER_SPECIALIZED
	move.b	#(PC_AUDIO_FD & 0x00FF), (PCM_FDL).l
.else
	move.w	h_audio_fd, d0
	move.b	d0, (PCM_FDL).l
.endif
	nop
	nop
.ifdef PLAYER_SPECIALIZED
	move.b	#((PC_AUDIO_FD >> 8) & 0x00FF), (PCM_FDH).l
.else
	lsr.w	#8, d0
	move.b	d0, (PCM_FDH).l
.endif
	nop
	nop
	move.b	#0x00, (PCM_LSL).l
	nop
	nop
	move.b	#0x00, (PCM_LSH).l
	nop
	nop
	/* PCM_ST is the high byte of the 16-bit sample address. Start at
	   SYNC_LEAD, where BODY-arm audio was written, instead of 0x0000 silence. */
	move.b	#0x30, (PCM_ST).l		/* SYNC_LEAD=0x3000 */
	nop
	nop
	/* 起動時からリードを SYNC_LEAD で確立する。PCM_ST と write_ptr を同じ
	   サンプル位置に置き、先頭リング無音を再生しない。 */
	move.w	#SYNC_LEAD, write_ptr
	clr.w	resync_count
	movem.l	(sp)+, d0-d2/a0
	rts

pcm_on:
	move.w	#1, pcm_running
	/* GPGX reloads a channel's address on the OFF write. Repeat OFF here so
	   PCM_ST=SYNC_LEAD is latched even when the channel was left selected during
	   the boot-prefix writes, then enable it. */
	move.b	#0xFF, (PCM_ONOFF).l
	move.b	#0xFE, (PCM_ONOFF).l
	rts

/* Decode one checkpointed IMA chunk from a0 to PCM_DEC_BUF. Signed deltas stay
   at the same offset in both physical 1M banks, while next-index/output tables
   are Sub-owned PRG-RAM. Each checkpoint records the continuous movie state;
   no decoder state is carried between frames. */
decode_adpcm_chunk:
	movem.l	d0-d7/a0-a4, -(sp)
	move.w	(a0)+, d6			/* checkpoint predictor (signed) */
	ext.l	d6
	add.l	#0x8000, d6			/* offset representation 0..0xFFFF */
	moveq	#0, d2
	move.b	(a0)+, d2			/* checkpoint step index 0..88 */
	addq.l	#1, a0				/* reserved byte */
	cmpi.w	#88, d2				/* corrupted control cannot walk beyond table */
	bls.s	1f
	moveq	#88, d2
1:
	lsl.w	#5, d2				/* full-table row offset=index*32 */
	lea	PCM_DEC_BUF, a1
	lea	ADPCM_DELTAS, a2
	lea	ADPCM_INDICES, a3
	lea	ADPCM_LUT, a4
	moveq	#0, d4				/* clamp result keeps upper word zero */
	PC_MOVE_W h_audio_bytes, PC_AUDIO_BYTES, d7
	lsr.w	#1, d7				/* two samples per packed byte */
	beq	adpcm_decode_done
	subq.w	#1, d7
	/* At low frame rates one N4 ADPCM decode lasts about 16 ms, longer than
	   the 13.3 ms CD-sector interval.  Poll the CDC at most every 512 packed
	   bytes so it cannot sit unattended for a whole sector while decoding.
	   The specialized 24/30 fps player emits none of this counter work. */
.ifdef PLAYER_SPECIALIZED
.if PC_FPS_INT < 24
	move.w	d7, d5
	andi.w	#0x01FF, d5			/* first poll at the next 512-byte boundary */
.endif
.else
	moveq	#-1, d5				/* high-rate generic path: DBRA never expires */
	cmpi.w	#0x03FF, pump_mask		/* 24/30 fps use the sparse pump profile */
	beq.s	adpcm_pump_ready
	move.w	d7, d5
	andi.w	#0x01FF, d5
adpcm_pump_ready:
.endif
adpcm_decode_loop:
	moveq	#0, d0
	move.b	(a0)+, d0
	move.w	d0, d1				/* save high nibble */
	andi.w	#0x000F, d0
	/* low nibble: pre-signed delta and pre-scaled next index */
	move.w	d2, d3
	add.w	d0, d3
	add.w	d0, d3				/* indices byte offset */
	move.w	(a3,d3.w), d2
	add.w	d3, d3				/* deltas long byte offset */
	add.l	(a2,d3.w), d6
	btst	#16, d6
	beq.s	adpcm_low_clamped
	spl	d4
	ext.w	d4
	move.l	d4, d6				/* clamp to 0 or 0xFFFF */
adpcm_low_clamped:
	move.w	d6, -(sp)
	move.b	(sp)+, d0			/* high byte of offset predictor */
	move.b	(a4,d0.w), (a1)+
	/* high nibble */
	move.w	d1, d0
	lsr.w	#4, d0
	move.w	d2, d3
	add.w	d0, d3
	add.w	d0, d3
	move.w	(a3,d3.w), d2
	add.w	d3, d3
	add.l	(a2,d3.w), d6
	btst	#16, d6
	beq.s	adpcm_high_clamped
	spl	d4
	ext.w	d4
	move.l	d4, d6
adpcm_high_clamped:
	move.w	d6, -(sp)
	move.b	(sp)+, d0
	move.b	(a4,d0.w), (a1)+
.ifdef PLAYER_SPECIALIZED
.if PC_FPS_INT < 24
	dbra	d5, adpcm_decode_no_pump
	bsr	pump_poll			/* preserves decoder registers and table pointers */
	move.w	#0x01FF, d5
adpcm_decode_no_pump:
.endif
.else
	dbra	d5, adpcm_decode_no_pump
	bsr	pump_poll
	move.w	#0x01FF, d5
adpcm_decode_no_pump:
.endif
	dbra	d7, adpcm_decode_loop
adpcm_decode_done:
	movem.l	(sp)+, d0-d7/a0-a4
	rts

write_wave_chunk:
	movem.l	d0-d5/a0-a1, -(sp)
	/* While PCM is stopped, append startup chunks from write_ptr.  Do not trust
	   the stale current address (especially after a replay loop), and never count
	   boot-time filling as a re-sync. */
	tst.w	pcm_running
	bne	wwc_live_sync
	moveq	#0, d5
	move.w	write_ptr, d2
	move.w	d2, cur_lead
	bra	wwc_sync_ready
wwc_live_sync:
	moveq	#0, d5
	move.b	(PCM_PLAY_H).l, d5
	lsl.w	#8, d5
	move.w	write_ptr, d2
	move.w	d2, d0
	sub.w	d5, d0
	andi.w	#RING_MASK, d0			/* d0 = lead(書込-再生) */
	move.w	d0, cur_lead			/* 計測: 現リードを記録(HUD表示) */
	cmp.w	#SYNC_MIN, d0
	blo	1f
	cmp.w	#SYNC_MAX, d0
	bls	wwc_sync_ready
1:
	addq.w	#1, resync_count		/* 計測: re-sync発生(リード逸脱で書込ジャンプ=乱れ) */
	move.w	d5, d2
	add.w	#SYNC_LEAD, d2
	andi.w	#RING_MASK, d2
wwc_sync_ready:
	PC_MOVE_W h_audio_bytes, PC_AUDIO_BYTES, d3	/* fixed audio bytes/frame */
	beq	wwc_done			/* avoid a 65536-byte loop on a corrupt zero value */
	/* issue #15 opt5: RF5C164 samples occupy every other byte, so MOVE.L plus
	   MOVEP.L writes four samples at once.  Outer 0x100-byte chunks preserve the
	   old pump positions and never cross a 0x1000 bank or 0x8000 ring boundary. */
	move.w	d2, d0
	lsr.w	#8, d0
	lsr.w	#4, d0
	ori.b	#0x80, d0
	move.b	d0, (PCM_CTRL).l		/* initial bank */
	move.w	d2, d4
	andi.w	#0x0FFF, d4
	add.w	d4, d4
	lea	(PCM_WAVE).l, a1
	adda.w	d4, a1				/* a1 = initial wave write address */
wwc_chunk:
	tst.w	d3
	beq	wwc_done
	/* Poll at the fps-adaptive logical boundary (0x100 at <=20fps, 0x200 at 30fps). */
	move.w	d2, d0
	PC_AND_W wave_pump_mask, PC_WAVE_PUMP_MASK, d0
	bne	1f
	bsr	pump_poll			/* pump_poll preserves a1 */
1:
	/* d4 = min(remaining, bytes to next 0x100 boundary); d5 keeps its length. */
	move.w	d2, d4
	andi.w	#0x00FF, d4
	move.w	#0x0100, d0
	sub.w	d4, d0
	move.w	d3, d4
	cmp.w	d0, d4
	bls	2f
	move.w	d0, d4
2:
	move.w	d4, d5

	/* A 68000 long read must be even-aligned.  An odd bitmap/entry length can
	   leave audio on an odd address, so scalar-copy one byte before MOVE.L. */
	move.l	a0, d0
	btst	#0, d0
	beq	wwc_aligned
	move.b	(a0)+, (a1)
	addq.w	#2, a1
	subq.w	#1, d4
	beq	wwc_chunk_done

wwc_aligned:
	/* 16-byte core: four contiguous reads to four interleaved PCM writes. */
	move.w	d4, d0
	lsr.w	#4, d0
	beq	wwc_groups4
	move.w	d0, d1
	subq.w	#1, d1
wwc_loop16:
	move.l	(a0)+, d0
	movep.l	d0, 0(a1)
	move.l	(a0)+, d0
	movep.l	d0, 8(a1)
	move.l	(a0)+, d0
	movep.l	d0, 16(a1)
	move.l	(a0)+, d0
	movep.l	d0, 24(a1)
	lea	32(a1), a1
	dbra	d1, wwc_loop16
	andi.w	#0x000F, d4

wwc_groups4:
	/* Remaining four-byte groups (zero to three). */
	move.w	d4, d1
	lsr.w	#2, d1
	beq	wwc_tail
	subq.w	#1, d1
wwc_loop4:
	move.l	(a0)+, d0
	movep.l	d0, 0(a1)
	lea	8(a1), a1
	dbra	d1, wwc_loop4
	andi.w	#0x0003, d4

wwc_tail:
	/* Scalar-copy the final zero to three bytes. */
	tst.w	d4
	beq	wwc_chunk_done
	subq.w	#1, d4
wwc_tail_loop:
	move.b	(a0)+, (a1)
	addq.w	#2, a1
	dbra	d4, wwc_tail_loop

wwc_chunk_done:
	add.w	d5, d2				/* advance the logical pointer by one chunk */
	sub.w	d5, d3
	/* Change bank only at 0x1000 boundaries and wrap 0x8000 to bank zero.
	   Match the old loop by applying an exact-end bank change before returning. */
	move.w	d2, d0
	andi.w	#0x0FFF, d0
	bne	wwc_chunk
	cmp.w	#WAVE_RING_END, d2
	blo	wwc_set_bank
	moveq	#0, d2
	moveq	#0, d0
	bra	wwc_write_bank
wwc_set_bank:
	move.w	d2, d0
	lsr.w	#8, d0
	lsr.w	#4, d0
wwc_write_bank:
	ori.b	#0x80, d0
	move.b	d0, (PCM_CTRL).l
	lea	(PCM_WAVE).l, a1
	bra	wwc_chunk

wwc_done:
	move.w	d2, write_ptr
	tst.w	pcm_running
	bne	1f
	sub.w	#SYNC_LEAD, d2
	andi.w	#RING_MASK, d2
	move.w	d2, cur_lead			/* boot HUD reports reserve, not absolute write address */
1:
	move.b	#0xC0, (PCM_CTRL).l
	movem.l	(sp)+, d0-d5/a0-a1
	rts

.global sp_int2
sp_int2:
	rts
.global sp_user
sp_user:
	rts

drv_init_tracklist:
	.byte	1, 0xFF
file_header:
	.asciz	"HEADER.DAT"
file_body:
	.asciz	"BODY.DAT"
	.align	2

bios_packet:
	.long	0, 0, 0, 0, 0
header_lba:
	.long	0
header_total:
	.long	0
body_lba:
	.long	0
body_total:
	.long	0
stream_remaining:
	.long	0
read_lba:
	.long	0				/* base LBA of the active HEADER/BODY read */
read_total:
	.long	0				/* sector count of the active read */
dr_dest:
	.long	0
prev_msf:
	.long	0
base_msf:
	.long	0				/* first-sector MSF of the active read; slip-recovery base */
slip_count:
	.word	0
	.word	0
ring_head:
	.long	0
ring_tail:
	.long	0
apply_tail:
	.long	0
apply_cur:
	.long	0
frame_idx:
	.word	0
drain_frame:
	.word	0
.ifndef PLAYER_SPECIALIZED
h_frames:
	.space 2
h_pool:
	.space 2				/* header pool slots; descriptor destination bound */
h_cells:
	.space 2				/* header cell count; raw-prefetch run bound */
h_bmbytes:
	.space 2
h_routing_sec:
	.space 2
h_prebuf_sec:
	.space 2
h_prebuf_pat:
	.space 4
h_f0_ctrl_sec:
	.space 2
h_f0_pat_sec:
	.space 2
h_paltab_sec:
	.space 2
pump_mask:
	.space 2				/* entry展開中pump頻度: 15fps=63(64件毎), 30fps=1023(末尾1回) */
wave_pump_mask:
	.space 2				/* wave書込みpump頻度: 15fps=0xFF(256B毎), 30fps=0x1FF(512B毎) */
h_audio_bytes:
	.space 2				/* decoded RF5C164 bytes/samples per frame */
h_audio_control_bytes:
	.space 2				/* PCM=same; ADPCM=4-byte checkpoint + samples/2 */
h_audio_fd:
	.space 2				/* v9 header offset 58: RF5C164 frequency delta */
	.if 0	/* v8 no longer stores the already-consumed nominal fps */
h_fps_int:
	.space 2				/* v4: nominal fps from header offset 56 */
	.endif
h_audio_pre_sec:
	.space 2				/* v17: BODY-arm audio sectors (one chunk per sector) */
h_body_arm_sec:
	.space 2				/* audio + frame0 control + frame0 patterns */
h_features:
	.space 2				/* offset 62: bit0 cold runs, bit1 authoritative fixed N */
sec_base:
	.space 2				/* floor(rate numerator/sec_mod), precomputed at header load */
sec_rem:
	.space 2				/* rate numerator mod sec_mod, precomputed at header load */
sec_mod:
	.space 2				/* rate accumulator modulus: fixed N uses 800, otherwise fps */
.endif
sec_acc:
	.space 2				/* v4: CD 1x レート累積器の余り(0..sec_mod-1) */
cur_fsec:
	.space 2				/* v4: 現コマのディスクセクタ数 fsec=max(total,ratedelta-lead) */
cur_n_ctrl:
	.space 2				/* 現コマrouting cache: leading control sectors */
cur_n_word:
	.space 2				/* leading payload sectors staged into parity WordBuf */
cur_total:
	.space 2				/* 現コマrouting cache: payload+control sectors */
lead:
	.space 2				/* v4: ディスクがCD 1x予定より先行しているセクタ数(≥0) */
f0_pat_addr:
	.space 4
drain_k:
	.word	0
write_ptr:
	.word	0
f0_expand:
	.word	0				/* !=0: frame0 cold pop is contiguous boot storage, not streaming ring */
.ifdef INCLUDE_WORDBUF_RING
word_write_ptr0:
	.long	0				/* next timed Wr0 sector destination */
word_write_ptr1:
	.long	0				/* next timed Wr1 sector destination */
word_level0:
	.word	0				/* logical live patterns, excluding sector padding */
word_level1:
	.word	0
word_owned_bank:
	.word	0				/* physical parity currently mapped to Sub */
word_pending_frame:
	.word	0				/* one routed slot owns all queued sectors */
word_pending_count:
	.word	0				/* zero to four queued 2 KiB sectors */
.endif
.if ring_tail-ring_head != 4
.error "Sub extension ring state layout changed"
.endif
.if apply_tail-ring_head != 8
.error "Sub extension APPLY tail layout changed"
.endif
.if apply_cur-ring_head != 12
.error "Sub extension APPLY cursor layout changed"
.endif
.if frame_idx-ring_head != 16
.error "Sub extension frame index layout changed"
.endif
.if write_ptr-drain_k != 2
.error "Sub extension write pointer layout changed"
.endif
.if f0_expand-drain_k != 4
.error "Sub extension frame-0 flag layout changed"
.endif
pcm_running:
	.word	0				/* 0=play headを読まずboot-time append, 1=live sync */
desync_count:
	.word	0				/* control同期マーカー不一致の累積(診断) */
resync_count:
	.word	0				/* 計測: 音声re-sync累積(リード逸脱=書込ジャンプ=乱れ) */
cur_lead:
	.word	0				/* 計測: 現コマの音声リード(write-play) */
.ifdef DEBUG
pf_ctrl_wait:
	.word	0				/* current-frame control wait pumps */
pf_body_wait:
	.word	0				/* prior BODY frame wait pumps */
.ifdef DEBUG_SUB_POLL_GAP
poll_last_tick:
	.word	0				/* stopwatch tick at previous poll entry or pump return */
poll_max_gap:
	.word	0				/* maximum outside-pump gap in 30.72 us ticks */
.endif
.ifdef DEBUG_PRGBUF_Q
ring_level:
	.word	0				/* signed logical PrgBuf balance in 32-byte patterns */
.ifndef DEBUG_PRGMIN_DIRECT
ring_frame_min:
	.word	0				/* signed minimum balance observed during this frame */
.endif
.endif
.endif

.ifdef INCLUDE_WORDBUF_RING
	.align 4
word_pending2:
	.space 0x800				/* third pending sector; resident image stays below 8 KiB */
.endif
sp_end:
