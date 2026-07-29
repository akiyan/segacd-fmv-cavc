/*
 * fontbench - gate-array Font bit vs CPU LUT 1bpp expansion - Sub (SP) side.
 *
 * Measures three ways to produce 32-byte 4bpp patterns on the Sub CPU, over
 * the same deterministic LFSR input, all destinations in Sub PRG-RAM:
 *
 *   FONT: 1bpp -> 4bpp through the gate-array font registers
 *         ($FF804C color, $FF804E bit, $FF8050-56 data readback)
 *   LUT : 1bpp -> 4bpp through a 256-entry x 4-byte PRG-RAM lookup table
 *   COPY: plain 32-byte 4bpp pattern copy (the current player's
 *         ef_run_pattern movem shape) as the baseline
 *
 * Timing: Sub-side stopwatch $FF800C (30.72 us/tick, 12-bit). Each variant
 * runs REPS passes over PATTERNS patterns, timed in CHUNK_PATTERNS chunks
 * (each chunk far below the 4096-tick wrap); tick deltas accumulate into a
 * 16-bit total reported live through COMSTAT1.
 *
 * Verification: FONT output vs LUT output are compared byte-exactly. The LUT
 * encodes this bench's assumed convention (fontbit bit 15 = leftmost pixel of
 * the pair of rows, font color high nibble = color of 1-bits, $FF8050 word =
 * pixels of bits 15..12). A nonzero mismatch count plus the first mismatching
 * word pair displayed by Main falsifies the assumption and shows the real
 * bit order. Checksums of both outputs allow an offline Python cross-check.
 *
 * Protocol (COMCMD0 from Main):
 *   CMD_PREP  (0x50): LFSR-fill input, build LUT, set font color.
 *   CMD_FONT  (0x51): timed font-register expansion.  COMSTAT1 = ticks.
 *   CMD_LUT   (0x52): timed LUT expansion.            COMSTAT1 = ticks.
 *   CMD_COPY  (0x53): timed 32-byte pattern copy.     COMSTAT1 = ticks.
 *   CMD_VERIFY(0x54): compare FONT vs LUT output.     COMSTAT1 = mismatches.
 *   CMD_OFS   (0x55): COMSTAT1 = first mismatch word index (0xFFFF = none).
 *   CMD_WA    (0x56): COMSTAT1 = FONT word at first mismatch.
 *   CMD_WB    (0x57): COMSTAT1 = LUT word at first mismatch.
 *   CMD_CKA   (0x58): COMSTAT1 = 16-bit word sum of FONT output.
 *   CMD_CKB   (0x59): COMSTAT1 = 16-bit word sum of LUT output.
 */

.equ SUB_GA_BASE, 0x00FF8000
.equ MEMMODE,     SUB_GA_BASE+0x0002
.equ STOPWATCH,   SUB_GA_BASE+0x000C	/* 12-bit, 30.72 us/tick */
.equ COMCMD0,     SUB_GA_BASE+0x0010
.equ COMSTAT0,    SUB_GA_BASE+0x0020
.equ COMSTAT1,    SUB_GA_BASE+0x0022
.equ FONTCOLOR,   SUB_GA_BASE+0x004C
.equ FONTBIT,     SUB_GA_BASE+0x004E
.equ FONTDATA,    SUB_GA_BASE+0x0050	/* 4 words: $FF8050/52/54/56 */

/* Sub PRG-RAM buffers, far above this 8 KiB SP image at 0x6000 and the
   BIOS-touched low region; no CD reads happen after boot in this bench. */
.equ IN_1BPP, 0x00010000	/* 16 KiB: PATTERNS x 8 bytes of 1bpp input */
.equ LUT,     0x00014000	/*  1 KiB: 256 entries x 4 bytes */
.equ OUT_A,   0x00020000	/* 64 KiB: FONT expansion output */
.equ OUT_B,   0x00030000	/* 64 KiB: LUT expansion output */
.equ OUT_C,   0x00040000	/* 64 KiB: COPY destination */

.equ PATTERNS,       2048
.equ CHUNK_PATTERNS, 512
.equ CHUNKS,         PATTERNS/CHUNK_PATTERNS
.equ REPS,           8

.equ COLOR_ZERO, 0x1		/* palette index for 0-bits */
.equ COLOR_ONE,  0xE		/* palette index for 1-bits */
.equ FONTCOLOR_W, (COLOR_ONE<<4)|COLOR_ZERO	/* assumed: high nibble = 1-bits */

.equ CMD_PREP,   0x50
.equ CMD_FONT,   0x51
.equ CMD_LUT,    0x52
.equ CMD_COPY,   0x53
.equ CMD_VERIFY, 0x54
.equ CMD_OFS,    0x55
.equ CMD_WA,     0x56
.equ CMD_WB,     0x57
.equ CMD_CKA,    0x58
.equ CMD_CKB,    0x59

.equ STAT_PREP_DONE, 0x0001
.equ STAT_DONE,      0x00D0

.text

sp_header:
	.ascii	"MAIN       "
	.byte	0
	.word	0x0100
	.word	0
	.long	0
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
	beq	command_loop
	moveq	#0, d0
	move.w	(COMCMD0).l, d0
	cmp.w	#CMD_PREP, d0
	beq	c_prep
	cmp.w	#CMD_FONT, d0
	beq	c_font
	cmp.w	#CMD_LUT, d0
	beq	c_lut
	cmp.w	#CMD_COPY, d0
	beq	c_copy
	cmp.w	#CMD_VERIFY, d0
	beq	c_verify
	cmp.w	#CMD_OFS, d0
	beq	c_ofs
	cmp.w	#CMD_WA, d0
	beq	c_wa
	cmp.w	#CMD_WB, d0
	beq	c_wb
	cmp.w	#CMD_CKA, d0
	beq	c_cka
	cmp.w	#CMD_CKB, d0
	beq	c_ckb
	/* unknown: just ack */
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait

c_prep:
	bsr	do_prep
	move.w	#STAT_PREP_DONE, (COMSTAT0).l
	bra	ack_wait
c_font:
	bsr	bench_font
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_lut:
	bsr	bench_lut
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_copy:
	bsr	bench_copy
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_verify:
	bsr	do_verify
	move.w	mis_count, (COMSTAT1).l
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_ofs:
	move.w	mis_off, (COMSTAT1).l
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_wa:
	move.w	mis_a, (COMSTAT1).l
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_wb:
	move.w	mis_b, (COMSTAT1).l
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_cka:
	move.w	cka, (COMSTAT1).l
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait
c_ckb:
	move.w	ckb, (COMSTAT1).l
	move.w	#STAT_DONE, (COMSTAT0).l
	bra	ack_wait

ack_wait:
	tst.w	(COMCMD0).l
	bne	ack_wait
	move.w	#0, (COMSTAT0).l
	bra	sp_main

/* ------------------------------------------------------------------ */
/* PREP: deterministic input + LUT + font color.                       */
/* ------------------------------------------------------------------ */
do_prep:
	movem.l	d0-d3/a0, -(sp)
	/* 16-bit Galois LFSR fill of IN_1BPP (8192 words), seed 0xACE1. */
	lea	(IN_1BPP).l, a0
	move.w	#0xACE1, d0
	move.w	#(PATTERNS*8/2)-1, d1
1:
	move.w	d0, (a0)+
	lsr.w	#1, d0
	bcc	2f
	eori.w	#0xB400, d0
2:
	dbra	d1, 1b

	/* LUT: entry i (0..255) = 4 bytes; bit 7 of i is the leftmost pixel,
	   1-bits become COLOR_ONE nibbles, 0-bits COLOR_ZERO nibbles. */
	lea	(LUT).l, a0
	moveq	#0, d1				/* i */
lut_entry:
	moveq	#0, d2				/* assembled 8 nibbles */
	moveq	#8-1, d3
lut_bit:
	lsl.l	#4, d2
	btst	d3, d1
	beq	1f
	ori.b	#COLOR_ONE, d2
	bra	2f
1:
	ori.b	#COLOR_ZERO, d2
2:
	dbra	d3, lut_bit
	move.l	d2, (a0)+
	addq.w	#1, d1
	cmpi.w	#256, d1
	bne	lut_entry

	move.w	#FONTCOLOR_W, (FONTCOLOR).l
	movem.l	(sp)+, d0-d3/a0
	rts

/* ------------------------------------------------------------------ */
/* Timed variants.  Shared wrapper shape:                              */
/*   d6 = rep counter, d2 = chunk counter, d7 = pattern counter,       */
/*   d4 = tick delta, d5 = running tick total (word),                  */
/*   a4 = source, a1 = destination; chunk t0 spills to chunk_t0.       */
/* ------------------------------------------------------------------ */

bench_font:
	movem.l	d0-d7/a0-a6, -(sp)
	move.w	#FONTCOLOR_W, (FONTCOLOR).l
	moveq	#0, d5
	move.w	#REPS-1, d6
bf_rep:
	lea	(IN_1BPP).l, a4
	lea	(OUT_A).l, a1
	move.w	#CHUNKS-1, d2
bf_chunk:
	move.w	(STOPWATCH).l, chunk_t0
	move.w	#CHUNK_PATTERNS-1, d7
bf_pat:
	move.w	(a4)+, (FONTBIT).l
	movem.l	(FONTDATA).l, d0-d1
	movem.l	d0-d1, (a1)
	move.w	(a4)+, (FONTBIT).l
	movem.l	(FONTDATA).l, d0-d1
	movem.l	d0-d1, 8(a1)
	move.w	(a4)+, (FONTBIT).l
	movem.l	(FONTDATA).l, d0-d1
	movem.l	d0-d1, 16(a1)
	move.w	(a4)+, (FONTBIT).l
	movem.l	(FONTDATA).l, d0-d1
	movem.l	d0-d1, 24(a1)
	lea	32(a1), a1
	dbra	d7, bf_pat
	move.w	(STOPWATCH).l, d4
	sub.w	chunk_t0, d4
	andi.w	#0x0FFF, d4
	add.w	d4, d5
	move.w	d5, (COMSTAT1).l
	dbra	d2, bf_chunk
	dbra	d6, bf_rep
	move.w	d5, ticks_font
	movem.l	(sp)+, d0-d7/a0-a6
	rts

bench_lut:
	movem.l	d0-d7/a0-a6, -(sp)
	moveq	#0, d5
	move.w	#REPS-1, d6
	lea	(LUT).l, a2
bl_rep:
	lea	(IN_1BPP).l, a4
	lea	(OUT_B).l, a1
	move.w	#CHUNKS-1, d2
bl_chunk:
	move.w	(STOPWATCH).l, chunk_t0
	move.w	#CHUNK_PATTERNS-1, d7
bl_pat:
	.rept	8
	clr.w	d0
	move.b	(a4)+, d0
	add.w	d0, d0
	add.w	d0, d0
	move.l	(a2,d0.w), (a1)+
	.endr
	dbra	d7, bl_pat
	move.w	(STOPWATCH).l, d4
	sub.w	chunk_t0, d4
	andi.w	#0x0FFF, d4
	add.w	d4, d5
	move.w	d5, (COMSTAT1).l
	dbra	d2, bl_chunk
	dbra	d6, bl_rep
	move.w	d5, ticks_lut
	movem.l	(sp)+, d0-d7/a0-a6
	rts

bench_copy:
	movem.l	d0-d7/a0-a6, -(sp)
	moveq	#0, d5
	move.w	#REPS-1, d6
bc_rep:
	lea	(OUT_B).l, a4			/* 4bpp source = LUT output */
	lea	(OUT_C).l, a1
	move.w	#CHUNKS-1, d2
bc_chunk:
	move.w	(STOPWATCH).l, chunk_t0
	move.w	#CHUNK_PATTERNS-1, d7
bc_pat:
	/* Same shape as the player's ef_run_pattern: 28-byte movem plus a
	   final move.l that must not clobber the postincrement base. */
	movem.l	(a4)+, d0-d1/d3/a2-a3/a5-a6	/* first 28 bytes */
	movem.l	d0-d1/d3/a2-a3/a5-a6, (a1)
	move.l	(a4)+, 28(a1)
	lea	32(a1), a1
	dbra	d7, bc_pat
	move.w	(STOPWATCH).l, d4
	sub.w	chunk_t0, d4
	andi.w	#0x0FFF, d4
	add.w	d4, d5
	move.w	d5, (COMSTAT1).l
	dbra	d2, bc_chunk
	dbra	d6, bc_rep
	move.w	d5, ticks_copy
	movem.l	(sp)+, d0-d7/a0-a6
	rts

/* ------------------------------------------------------------------ */
/* VERIFY: word-compare OUT_A vs OUT_B, then 16-bit word sums.         */
/* ------------------------------------------------------------------ */
do_verify:
	movem.l	d0-d7/a0-a1, -(sp)
	lea	(OUT_A).l, a0
	lea	(OUT_B).l, a1
	moveq	#0, d3				/* mismatch count */
	move.w	#0xFFFF, d4			/* first mismatch word index */
	moveq	#0, d6				/* current word index */
	move.w	#(PATTERNS*32/2)-1, d7
1:
	move.w	(a0)+, d0
	cmp.w	(a1)+, d0
	beq	2f
	addq.w	#1, d3
	cmpi.w	#0xFFFF, d4
	bne	2f
	move.w	d6, d4
2:
	addq.w	#1, d6
	dbra	d7, 1b
	move.w	d3, mis_count
	move.w	d4, mis_off

	moveq	#0, d0
	moveq	#0, d1
	cmpi.w	#0xFFFF, d4
	beq	3f
	moveq	#0, d5
	move.w	d4, d5
	add.l	d5, d5				/* byte offset */
	lea	(OUT_A).l, a0
	move.w	(a0,d5.l), d0
	lea	(OUT_B).l, a0
	move.w	(a0,d5.l), d1
3:
	move.w	d0, mis_a
	move.w	d1, mis_b

	lea	(OUT_A).l, a0
	bsr	sum_words
	move.w	d0, cka
	lea	(OUT_B).l, a0
	bsr	sum_words
	move.w	d0, ckb
	movem.l	(sp)+, d0-d7/a0-a1
	rts

/* a0 = 64 KiB buffer -> d0 = 16-bit sum of its big-endian words. */
sum_words:
	move.l	d7, -(sp)
	moveq	#0, d0
	move.w	#(PATTERNS*32/2)-1, d7
1:
	add.w	(a0)+, d0
	dbra	d7, 1b
	move.l	(sp)+, d7
	rts

.global sp_int2
sp_int2:
	rts

.global sp_user
sp_user:
	rts

.bss
	.align	2
chunk_t0:
	.space	2
ticks_font:
	.space	2
ticks_lut:
	.space	2
ticks_copy:
	.space	2
mis_count:
	.space	2
mis_off:
	.space	2
mis_a:
	.space	2
mis_b:
	.space	2
cka:
	.space	2
ckb:
	.space	2

sp_end:
