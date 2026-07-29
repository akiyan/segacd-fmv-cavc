/*
 * fontbench - gate-array Font bit vs CPU LUT 1bpp expansion - Main (IP) side.
 *
 * Drives the Sub-side bench phases and shows every result as fixed-position
 * hex rows (hexfont glyphs, plane A), OCR-friendly like the DEBUG HUD.
 * Layout (all values 4 hex digits at column 4, label digit at column 2):
 *
 *   row  2:  0 FB01   build magic (OCR anchor)
 *   row  4:  1 tttt   FONT ticks (font-register expansion, 30.72 us/tick)
 *   row  6:  2 tttt   LUT ticks  (256x4B table expansion)
 *   row  8:  3 tttt   COPY ticks (baseline 32-byte pattern copy)
 *   row 10:  4 mmmm   VERIFY mismatch words (FONT vs LUT output; 0000 = match)
 *   row 12:  5 oooo   first mismatch word index (FFFF = none)
 *   row 14:  6 aaaa   FONT word at first mismatch
 *   row 16:  7 bbbb   LUT  word at first mismatch
 *   row 18:  8 ssss   16-bit word sum of FONT output
 *   row 20:  9 ssss   16-bit word sum of LUT output
 *
 * Backdrop: blue=FONT, yellow=LUT, magenta=COPY, cyan=VERIFY, green=done.
 * Interrupts stay off; frames pass via polling the VDP vblank flag.
 */

.equ STACK, 0x00FFFD00

.equ BIOS_CLEAR_VRAM, 0x000002A0
.equ BIOS_LOAD_DEFAULT_VDP_REGS, 0x000002AC
.equ BIOS_VDP_DISP_ENABLE, 0x000002D8
.equ BIOS_CLEAR_COMM, 0x00000340

.equ VDP_DATA, 0x00C00000
.equ VDP_CTRL, 0x00C00004

.equ GA_COMCMD0, 0x00A12010
.equ GA_COMSTAT0, 0x00A12020
.equ GA_COMSTAT1, 0x00A12022

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
.equ STAT_DONE, 0x00D0

.equ MAGIC, 0xFB01

.equ NAME_A, 0xC000

.equ MAGIC_CELL, NAME_A+(2*64+4)*2
.equ FONT_CELL,  NAME_A+(4*64+4)*2
.equ LUT_CELL,   NAME_A+(6*64+4)*2
.equ COPY_CELL,  NAME_A+(8*64+4)*2
.equ MIS_CELL,   NAME_A+(10*64+4)*2
.equ OFS_CELL,   NAME_A+(12*64+4)*2
.equ WA_CELL,    NAME_A+(14*64+4)*2
.equ WB_CELL,    NAME_A+(16*64+4)*2
.equ CKA_CELL,   NAME_A+(18*64+4)*2
.equ CKB_CELL,   NAME_A+(20*64+4)*2

.equ COL_FONT,   0x0E00		/* blue    */
.equ COL_LUT,    0x00EE		/* yellow  */
.equ COL_COPY,   0x0E0E		/* magenta */
.equ COL_VERIFY, 0x0EE0		/* cyan    */
.equ COL_DONE,   0x00E0		/* green   */

.text

	.incbin "security.bin"

	bra.w	ip_entry
	.org	0x584

.global ip_entry
ip_entry:
	move.w	#0x2700, sr
	lea	STACK, sp

	jsr	BIOS_LOAD_DEFAULT_VDP_REGS
	jsr	BIOS_CLEAR_VRAM
	jsr	BIOS_CLEAR_COMM

	move.w	#0x8230, (VDP_CTRL).l		/* plane A name table = 0xC000 */
	move.w	#0x9001, (VDP_CTRL).l		/* plane size 64x32          */
	move.w	#0x8C00, (VDP_CTRL).l		/* reg12 H32: native 256x224 for exact OCR */
	bsr	load_font
	move.w	#COL_FONT, d0
	bsr	set_palette
	jsr	BIOS_VDP_DISP_ENABLE

	/* Static labels + zero values + magic. */
	bsr	print_labels
	move.w	#MAGIC, d0
	move.l	#MAGIC_CELL, d1
	bsr	print_hex16

	/* Untimed data/LUT preparation on the Sub. */
	move.w	#CMD_PREP, d0
	bsr	sub_command

	/* --- FONT phase (live ticks) --- */
	move.w	#CMD_FONT, d0
	move.l	#FONT_CELL, d1
	bsr	run_bench_phase

	/* --- LUT phase --- */
	move.w	#COL_LUT, d0
	bsr	set_palette
	move.w	#CMD_LUT, d0
	move.l	#LUT_CELL, d1
	bsr	run_bench_phase

	/* --- COPY phase --- */
	move.w	#COL_COPY, d0
	bsr	set_palette
	move.w	#CMD_COPY, d0
	move.l	#COPY_CELL, d1
	bsr	run_bench_phase

	/* --- VERIFY + info readouts --- */
	move.w	#COL_VERIFY, d0
	bsr	set_palette
	move.w	#CMD_VERIFY, d0
	bsr	info_command
	move.l	#MIS_CELL, d1
	bsr	print_hex16
	move.w	#CMD_OFS, d0
	bsr	info_command
	move.l	#OFS_CELL, d1
	bsr	print_hex16
	move.w	#CMD_WA, d0
	bsr	info_command
	move.l	#WA_CELL, d1
	bsr	print_hex16
	move.w	#CMD_WB, d0
	bsr	info_command
	move.l	#WB_CELL, d1
	bsr	print_hex16
	move.w	#CMD_CKA, d0
	bsr	info_command
	move.l	#CKA_CELL, d1
	bsr	print_hex16
	move.w	#CMD_CKB, d0
	bsr	info_command
	move.l	#CKB_CELL, d1
	bsr	print_hex16

	move.w	#COL_DONE, d0
	bsr	set_palette
hang:
	bra	hang

/* d0 = bench command, d1 = result cell.  Sends the command, live-updates the
   cell from COMSTAT1 each frame, prints the final value, handshakes. */
run_bench_phase:
	movem.l	d2-d3, -(sp)
	move.w	d0, d2
	move.l	d1, d3
	move.w	d2, (GA_COMCMD0).l
1:
	bsr	wait_vblank
	move.w	(GA_COMSTAT1).l, d0
	move.l	d3, d1
	bsr	print_hex16
	cmp.w	#STAT_DONE, (GA_COMSTAT0).l
	bne	1b
	bsr	finish_handshake
	move.w	(GA_COMSTAT1).l, d0
	move.l	d3, d1
	bsr	print_hex16
	movem.l	(sp)+, d2-d3
	rts

/* d0 = command -> d0 = COMSTAT1 result (word), fully handshaked. */
info_command:
	move.w	d0, (GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	beq	1b
	bsr	finish_handshake
	move.w	(GA_COMSTAT1).l, d0
	rts

sub_command:
	move.w	d0, (GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	beq	1b
finish_handshake:
	move.w	#0, (GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	bne	1b
	rts

print_labels:
	moveq	#0, d0
	move.l	#MAGIC_CELL-4, d1
	bsr	print_digit
	moveq	#1, d0
	move.l	#FONT_CELL-4, d1
	bsr	print_digit
	moveq	#2, d0
	move.l	#LUT_CELL-4, d1
	bsr	print_digit
	moveq	#3, d0
	move.l	#COPY_CELL-4, d1
	bsr	print_digit
	moveq	#4, d0
	move.l	#MIS_CELL-4, d1
	bsr	print_digit
	moveq	#5, d0
	move.l	#OFS_CELL-4, d1
	bsr	print_digit
	moveq	#6, d0
	move.l	#WA_CELL-4, d1
	bsr	print_digit
	moveq	#7, d0
	move.l	#WB_CELL-4, d1
	bsr	print_digit
	moveq	#8, d0
	move.l	#CKA_CELL-4, d1
	bsr	print_digit
	moveq	#9, d0
	move.l	#CKB_CELL-4, d1
	bsr	print_digit
	rts

load_font:
	move.l	#0x40200000, (VDP_CTRL).l	/* VRAM write at tile 1 (byte 0x20) */
	lea	hexfont, a0
	move.w	#(512/2)-1, d0
1:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d0, 1b
	rts

/* d0 = colour 0 (state/backdrop); colour 1 fixed white. */
set_palette:
	move.l	#0xC0000000, (VDP_CTRL).l
	move.w	d0, (VDP_DATA).l
	move.w	#0x0EEE, (VDP_DATA).l
	rts

/* d0 = nibble, d1 = name-table byte address. */
print_digit:
	movem.l	d0-d1, -(sp)
	move.w	d0, -(sp)
	move.l	d1, d0
	bsr	vram_write_cmd
	move.w	(sp)+, d0
	andi.w	#0x000F, d0
	addq.w	#1, d0			/* glyph tile = 1 + nibble */
	move.w	d0, (VDP_DATA).l
	movem.l	(sp)+, d0-d1
	rts

/* d0 = value (word), d1 = name-table byte address. */
print_hex16:
	movem.l	d0-d3, -(sp)
	move.w	d0, d3
	move.l	d1, d0
	bsr	vram_write_cmd
	moveq	#4-1, d2
1:
	rol.w	#4, d3
	move.w	d3, d0
	andi.w	#0x000F, d0
	addq.w	#1, d0			/* glyph tile = 1 + nibble */
	move.w	d0, (VDP_DATA).l
	dbra	d2, 1b
	movem.l	(sp)+, d0-d3
	rts

vram_write_cmd:
	and.l	#0x0000FFFF, d0
	lsl.l	#2, d0
	lsr.w	#2, d0
	swap	d0
	or.l	#0x40000000, d0
	move.l	d0, (VDP_CTRL).l
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

	.data
	.align 2
hexfont:
	.incbin "hexfont.bin"
