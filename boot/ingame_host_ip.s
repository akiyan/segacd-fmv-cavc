/*
 * In-game player test host, Main CPU side.
 *
 * A stand-in for a game that embeds the in-game player: it keeps its own
 * display (planes at 0xC000/0xE000, sprites at 0xF000, horizontal scroll at
 * 0xF400), its own level-6 frame counter and level-4 horizontal interrupt,
 * and its own data in the low 172 KiB of 2M Word RAM. It loads the in-game
 * Main module into Main RAM at INGAME_MAIN_BASE, asks its Sub program to
 * start the in-game Sub module, calls the Main module, and then checks what
 * the movie left behind:
 *
 *   row 2: status, frames, late frames, largest lateness, slips, desyncs
 *   row 3: Sub status, Sub slips, Word-RAM errors, VRAM errors (font and
 *          plane B), interrupt check (0 = both counters run again),
 *          play count
 *
 * The host's horizontal interrupt fires three times a frame only to prove
 * that the movie hands it back; the movie masks it while it plays. The
 * result screen stays up for five seconds, then the movie plays again.
 *
 * Built with HOST_LOAD_LINES=N, the horizontal interrupt instead stands in
 * for a music driver that keeps running during the movie: once per frame it
 * starts at line 8, busy-waits until N lines later, then holds the Sub bus
 * and reads PRG-RAM for about 400 cycles. The movie is asked to keep it
 * (flag bit 1). Row 4 then shows, for the play: load runs, runs that ended
 * in the vertical blank, runs that took over two lines longer than asked
 * (preempted), the latest end line, and the largest extra lines.
 */
	.include "sub_boot.inc"

.equ STACK, 0x00FFFD00
.equ BIOS_CLEAR_VRAM,            0x000002A0
.equ BIOS_LOAD_DEFAULT_VDP_REGS, 0x000002AC
.equ BIOS_CLEAR_COMM,            0x00000340
.equ EXVEC_LEVEL6, 0x00FFFD08		/* BIOS jump table: level 6 target */
.equ GA_HINT_VECTOR, 0x00A12006
.equ GA_MEMMODE, 0x00A12002
.equ GA_COMCMD0, 0x00A12010
.equ GA_COMSTAT0, 0x00A12020
.equ GA_COMSTAT1, 0x00A12022
.equ GA_COMSTAT2, 0x00A12024
.equ VDP_DATA, 0x00C00000
.equ VDP_CTRL, 0x00C00004
.equ VDP_HV,   0x00C00008
.equ GA_SUB_CTRL, 0x00A12001
.ifdef HOST_LOAD_LINES
.equ HINT_LINE, 7			/* first interrupt after line 7: work from line 8 */
.equ LOAD_BUS_WORDS, 16			/* about 400 cycles of PRG-RAM reads */
.equ MOVIE_FLAGS, 3			/* restore registers, keep this interrupt */
.else
.equ MOVIE_FLAGS, 1
.endif

.equ WORD_RAM, 0x00200000
.equ HOST_WORD_BYTES, 176128		/* the game's script, tables and font */
.equ PLANE_A, 0xC000
.equ PLANE_B, 0xE000
.equ HSCROLL, 0xF400
.equ FONT_TILE, 1400			/* host tiles above the movie's pool */
.equ FONT_ADDR, FONT_TILE*32
.equ FONT_TILES, 16

.equ REG0, 0x8014			/* horizontal interrupt enabled */
.equ REG1, 0x8174			/* display, VInt, DMA, mode 5 */
.equ REG2, 0x8200|(PLANE_A>>10)
.equ REG4, 0x8400|(PLANE_B>>13)
.equ REG7, 0x8700

.equ ST_READY,   1
.equ ST_DONE,    2
.equ ST_RUNNING, 3
.equ CMD_PLAY,   1
.equ CMD_ACK,    2
.equ CMD_INIT,   3

	.text
	.include "disc_region.inc"
	.incbin "security.bin"
	bra.w	ip_entry
	.org	DISC_IP_ENTRY_OFFSET

ip_entry:
	wait_sub_boot STAT_SUB_BOOTED
	move.w	#0x2700, sr
	lea	STACK, sp
	jsr	BIOS_LOAD_DEFAULT_VDP_REGS
	jsr	BIOS_CLEAR_VRAM
	jsr	BIOS_CLEAR_COMM
	lea	VDP_CTRL, a6
	lea	VDP_DATA, a5
	move.w	#0x8004, (a6)
	move.w	#0x8134, (a6)			/* display off while drawing */
	move.w	#REG2, (a6)
	move.w	#REG4, (a6)
	move.w	#0x8500|(0xF000>>9), (a6)	/* sprites 0xF000 */
	move.w	#0x8B00, (a6)
	move.w	#0x8C81, (a6)			/* H40 */
	move.w	#0x8D00|(HSCROLL>>10), (a6)
	move.w	#0x8F02, (a6)
	move.w	#0x9001, (a6)			/* 64x32 */
.ifdef HOST_LOAD_LINES
	move.w	#0x8A00|HINT_LINE, (a6)		/* first interrupt of the frame at line 8 */
.else
	move.w	#0x8A5F, (a6)			/* horizontal interrupt every 96 lines */
.endif
	move.w	#REG7, (a6)
	bsr	load_font
	/* The Sub program starts the drive and finds the movie files. */
	move.w	#CMD_INIT, (GA_COMCMD0).l
1:
	cmpi.w	#ST_READY, (GA_COMSTAT0).l
	bne.s	1b
	move.w	#0, (GA_COMCMD0).l
	/* The game's own data: low 2M Word RAM. */
1:
	btst	#0, (GA_MEMMODE+1).l
	beq.s	1b				/* wait for Main ownership */
	lea	WORD_RAM, a0
	move.l	#HOST_WORD_BYTES/2-1, d1
	moveq	#0, d0
1:
	move.w	d0, d2
	eori.w	#0x5A5A, d2
	move.w	d2, (a0)+
	addq.w	#1, d0
	subq.l	#1, d1
	bpl.s	1b
	/* The game's interrupts. */
	move.l	#host_vint, (EXVEC_LEVEL6).l
	move.l	#host_hint, d0
	move.w	d0, (GA_HINT_VECTOR).l
	/* The Main module, loaded where it is linked to run. */
	lea	main_module, a0
	movea.l	8(a0), a1			/* link base */
	move.l	12(a0), d0			/* image bytes */
	lsr.l	#1, d0
	subq.l	#1, d0
1:
	move.w	(a0)+, (a1)+
	subq.l	#1, d0
	bpl.s	1b

play_again:
	/* Display on first: the VBlank flag stays set while it is off. */
	move.w	#REG0, (a6)
	move.w	#REG1, (a6)
	bsr	host_screen
	move.w	#0x2300, sr
	move.w	#90, d0
	bsr	wait_frames
	/* The game stops its music here; this host has none. */
	move.w	#CMD_PLAY, (GA_COMCMD0).l
1:
	cmpi.w	#ST_RUNNING, (GA_COMSTAT0).l
	beq.s	2f
	cmpi.w	#ST_DONE, (GA_COMSTAT0).l
	bne.s	1b
	moveq	#-1, d0				/* the Sub could not start the module */
	bra.s	3f
2:
	lea	main_module, a0
	movea.l	8(a0), a1
	movea.l	20(a1), a1			/* entry */
	lea	movie_params, a0
.ifdef HOST_LOAD_LINES
	lea	load_stats, a2
	clr.l	(a2)+
	clr.l	(a2)+
	clr.w	(a2)+
	move.w	#1, load_counting
.endif
	jsr	(a1)
.ifdef HOST_LOAD_LINES
	clr.w	load_counting
.endif
3:
	lea	results, a0
	movem.w	d0-d5, (a0)
	addq.w	#1, play_count
1:
	cmpi.w	#ST_DONE, (GA_COMSTAT0).l
	bne.s	1b
	move.w	(GA_COMSTAT1).l, sub_status
	move.w	(GA_COMSTAT2).l, sub_slips
	move.w	#CMD_ACK, (GA_COMCMD0).l
1:
	cmpi.w	#ST_READY, (GA_COMSTAT0).l
	bne.s	1b
	move.w	#0, (GA_COMCMD0).l
	bsr	check_after_movie
	bsr	result_screen
	move.w	#300, d0
	bsr	wait_frames
	bra	play_again

/* Count Word-RAM, VRAM and interrupt differences after the movie. */
check_after_movie:
	clr.w	word_errors
1:
	move.b	(GA_MEMMODE+1).l, d0
	andi.b	#0x05, d0
	cmpi.b	#0x01, d0			/* 2M, Main owns Word RAM */
	beq.s	2f
	move.w	#0xFFFF, word_errors
	bra.s	4f
2:
	lea	WORD_RAM, a0
	move.l	#HOST_WORD_BYTES/2-1, d1
	moveq	#0, d0
3:
	move.w	d0, d2
	eori.w	#0x5A5A, d2
	cmp.w	(a0)+, d2
	beq.s	5f
	addq.w	#1, word_errors
5:
	addq.w	#1, d0
	subq.l	#1, d1
	bpl.s	3b
4:
	/* The host font sits above the movie's 1,279-tile pool. No interrupt
	   may write a VDP register during these reads. */
	move.w	#0x2700, sr
	clr.w	vram_errors
	move.l	#FONT_ADDR, d0
	bsr	vram_read_cmd
	move.l	d0, (a6)
	lea	font_expanded, a0
	move.w	#FONT_TILES*16-1, d1
1:
	move.w	(a5), d0
	cmp.w	(a0)+, d0
	beq.s	2f
	addq.w	#1, vram_errors
2:
	dbra	d1, 1b
	/* Plane B still holds the host's pattern. */
	move.l	#PLANE_B, d0
	bsr	vram_read_cmd
	move.l	d0, (a6)
	moveq	#0, d2
	move.w	#64*32-1, d1
1:
	move.w	d2, d0
	andi.w	#0x000F, d0
	addi.w	#FONT_TILE, d0
	cmp.w	(a5), d0
	beq.s	2f
	addq.w	#1, vram_errors
2:
	addq.w	#1, d2
	dbra	d1, 1b
	/* Both host interrupts run again. */
	move.w	#0x2300, sr
	move.w	frame_count, d2
	move.w	hint_count, d3
	move.w	#10, d0
	bsr	wait_frames_hint
	moveq	#0, d4
	cmp.w	frame_count, d2
	bne.s	1f
	moveq	#1, d4
1:
	cmp.w	hint_count, d3
	bne.s	1f
	ori.w	#2, d4
1:
	move.w	d4, int_check
	rts

/* Wait d0 frames on the host frame counter (horizontal interrupt as is). */
wait_frames_hint:
	move.w	frame_count, d1
	add.w	d0, d1
1:
	cmp.w	frame_count, d1
	bne.s	1b
	rts
wait_frames:
	bra.s	wait_frames_hint

/* d0 = VRAM byte address -> VRAM read command. */
vram_read_cmd:
	andi.l	#0x0000FFFF, d0
	lsl.l	#2, d0
	lsr.w	#2, d0
	swap	d0
	rts
vram_write_cmd:
	bsr.s	vram_read_cmd
	ori.l	#0x40000000, d0
	rts

/* Expand the 1-bit debug font to colours 1/15 and upload it. */
load_font:
	lea	dbgfont, a0
	lea	font_expanded, a1
	move.w	#FONT_TILES*16-1, d1
1:
	move.w	(a0)+, d0
	move.w	d0, d2
	lsl.w	#1, d2
	or.w	d2, d0
	lsl.w	#1, d2
	or.w	d2, d0
	lsl.w	#1, d2
	or.w	d2, d0
	ori.w	#0x1111, d0
	move.w	d0, (a1)+
	dbra	d1, 1b
	move.l	#FONT_ADDR, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	lea	font_expanded, a0
	move.w	#FONT_TILES*16-1, d1
1:
	move.w	(a0)+, (a5)
	dbra	d1, 1b
	rts

/* The game's screen: its colours, plane B filled with a hex pattern. */
host_screen:
	move.w	#0x2700, sr
	bsr	wait_vblank_poll
	move.l	#0xC0000000, (a6)
	lea	host_cram, a0
	moveq	#16-1, d1
1:
	move.w	(a0)+, (a5)
	dbra	d1, 1b
	move.l	#PLANE_B, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	moveq	#0, d2
	move.w	#64*32-1, d1
1:
	move.w	d2, d0
	andi.w	#0x000F, d0
	addi.w	#FONT_TILE, d0
	move.w	d0, (a5)
	addq.w	#1, d2
	dbra	d1, 1b
	/* plane A empty, no scroll */
	move.l	#PLANE_A, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	moveq	#0, d0
	move.w	#64*32/2-1, d1
1:
	move.l	d0, (a5)
	dbra	d1, 1b
	move.l	#HSCROLL, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	moveq	#0, d0
	move.l	d0, (a5)
	move.l	#0x40000010, (a6)		/* VSRAM 0..1 */
	move.l	d0, (a5)
	rts

wait_vblank_poll:
1:
	move.w	(a6), d0
	btst	#3, d0
	bne.s	1b
1:
	move.w	(a6), d0
	btst	#3, d0
	beq.s	1b
	rts

/* Results on plane A rows 2 and 3, 4 hex digits per value. */
result_screen:
	bsr	host_screen
	move.l	#PLANE_A+(2*64+1)*2, d0
	lea	results, a0
	moveq	#6-1, d3
	bsr	put_row
	move.l	#PLANE_A+(3*64+1)*2, d0
	lea	sub_status, a0
	moveq	#6-1, d3
	bsr	put_row
.ifdef HOST_LOAD_LINES
	move.l	#PLANE_A+(4*64+1)*2, d0
	lea	load_stats, a0
	moveq	#5-1, d3
	bsr	put_row
.endif
	move.w	#0x2300, sr
	rts

/* d0 = VRAM address, a0 = words, d3 = count-1: "XXXX " each. */
put_row:
	bsr	vram_write_cmd
	move.l	d0, (a6)
1:
	move.w	(a0)+, d2
	moveq	#4-1, d4
2:
	rol.w	#4, d2
	move.w	d2, d0
	andi.w	#0x000F, d0
	addi.w	#FONT_TILE+0x8000, d0		/* high priority over plane B */
	move.w	d0, (a5)
	dbra	d4, 2b
	move.w	#0, (a5)
	dbra	d3, 1b
	rts

host_vint:
	addq.w	#1, frame_count
	rte
host_hint:
.ifndef HOST_LOAD_LINES
	addq.w	#1, hint_count
	rte
.else
	movem.l	d0-d2/a0, -(sp)
	addq.w	#1, hint_count
	moveq	#0, d1
	move.b	(VDP_HV).l, d1			/* start line */
	cmpi.b	#HINT_LINE+4, d1
	bhs	hh_second
	/* The frame's first interrupt: no other until the next blank. One
	   control-word write; the movie's VDP access is all in its V-int. */
	move.w	#0x8AFF, (VDP_CTRL).l
	/* The driver's work: busy-wait N lines ... */
	move.w	d1, d2
	addi.w	#HOST_LOAD_LINES, d2
1:
	moveq	#0, d0
	move.b	(VDP_HV).l, d0
	cmp.w	d1, d0
	blo.s	2f				/* wrapped into the next frame */
	cmp.w	d2, d0
	blo.s	1b
2:
	/* ... then read song data from PRG-RAM with the Sub bus held. */
	bset	#1, (GA_SUB_CTRL).l
3:
	btst	#1, (GA_SUB_CTRL).l
	beq.s	3b
	lea	0x00020000, a0
	moveq	#LOAD_BUS_WORDS-1, d0
3:
	move.w	(a0)+, d2
	dbra	d0, 3b
	bclr	#1, (GA_SUB_CTRL).l
	tst.w	load_counting
	beq.s	hh_done
	moveq	#0, d0
	move.b	(VDP_HV).l, d0			/* end line */
	addq.w	#1, load_stats+0		/* runs */
	cmpi.w	#0xE0, d0
	blo.s	4f
	addq.w	#1, load_stats+2		/* ended in the vertical blank */
4:
	cmp.w	d1, d0
	bhs.s	5f
	addq.w	#1, load_stats+2		/* wrapped: ran past the blank */
	addi.w	#0x100, d0
5:
	cmp.w	load_stats+6, d0
	bls.s	6f
	move.w	d0, load_stats+6		/* latest end line */
6:
	sub.w	d1, d0
	subi.w	#HOST_LOAD_LINES, d0		/* extra lines beyond the asked load */
	cmpi.w	#2, d0
	bls.s	7f
	addq.w	#1, load_stats+4		/* preempted */
7:
	cmp.w	load_stats+8, d0
	ble.s	hh_done
	move.w	d0, load_stats+8
	bra.s	hh_done
hh_second:
	/* The frame's second interrupt: the counter now holds 0xFF, so restore
	   the line for the next frame's first interrupt. */
	move.w	#0x8A00|HINT_LINE, (VDP_CTRL).l
hh_done:
	movem.l	(sp)+, d0-d2/a0
	rte
.endif

	.align	2
host_cram:
	.word	0x0000, 0x0020, 0x0260, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000
	.word	0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0EEE
movie_params:
	.word	PLANE_A			/* movie name table */
	.word	HSCROLL
	.word	REG0
	.word	REG1
	.word	REG2
	.word	REG4
	.word	REG7
	.long	EXVEC_LEVEL6
	.word	MOVIE_FLAGS		/* restore the display registers (+ keep H-int) */
dbgfont:
	.incbin	"dbgfont.bin"
	.align	2
main_module:
	.incbin	"MOVIEM.BIN"
	.align	2

	.bss
frame_count:	.space 2
hint_count:	.space 2
results:	.space 12		/* status, frames(lo), late, max late, slips, desyncs */
sub_status:	.space 2
sub_slips:	.space 2
word_errors:	.space 2
vram_errors:	.space 2
int_check:	.space 2
play_count:	.space 2
.ifdef HOST_LOAD_LINES
load_stats:	.space 10		/* runs, in blank, preempted, latest end, max extra */
load_counting:	.space 2
.endif
font_expanded:	.space FONT_TILES*32
