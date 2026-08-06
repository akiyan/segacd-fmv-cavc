/*
 * Separate multi-video build - Main CPU menu.
 *
 * The menu is a small H40-only program.  The resident Sub launcher loads one
 * specialized movie IP image into the selected Word-RAM staging slot; this
 * program copies it to Main PRG-RAM and transfers control.  A movie's return
 * path restores this same image from a duplicate kept in both Word-RAM banks.
 */

.equ STACK,          0x00FFFD00
.equ BIOS_CLEAR_VRAM,0x000002A0
.equ BIOS_LOAD_DEFAULT_VDP_REGS, 0x000002AC
.equ BIOS_VDP_DISP_ENABLE, 0x000002D8

.equ VDP_DATA,       0x00C00000
.equ VDP_CTRL,       0x00C00004
.equ VDP_HV,         0x00C00008
.equ GA_COMCMD0,     0x00A12010
.equ GA_COMCMD1,     0x00A12012
.equ GA_COMSTAT0,    0x00A12020

.equ PROBE_BANK,     0x00200000
.equ MENU_MAP,       0x0000E000
.equ MENU_FONT_ADDR, 0x00000020
.equ MENU_FONT_BYTES,96*32
.equ MAP_WORDS,      64*32

.equ JOY_DATA,       0x00A10003
.equ JOY_CTRL,       0x00A10009
.equ JOY_UP,         0x0001
.equ JOY_DOWN,       0x0002
.equ JOY_C,          0x0020
.equ JOY_A,          0x0040

.equ MENU_PALETTE_ATTR, 0x2000
.equ CMD_MENU_LOAD, 0x0052
.equ STAT_MENU_READY, 0x8005
.equ STAT_MENU_IP_READY, 0x8006
.equ STAT_PLAYER_READY, 0x8007
.equ PLAYER_IP_STAGE_OFF, 0x00005000
.equ PLAYER_ENTRY,   0x00FF0000
.equ MULTI_LOOP_FLAG_MAIN, 0x00FFB1F0
.equ MULTI_RESTORE_CODE_ADDR, 0x00FF8880

	.include "multimovie_ip.inc"

.text

	.incbin "security.bin"

	bra.w	ip_entry
	.org	0x584

.global ip_entry
ip_entry:
	move.w	#0x2700, sr
	lea	STACK, sp
	clr.w	(MULTI_LOOP_FLAG_MAIN).l
	move.w	#0, selected
	move.w	#0, viewport_start
	move.w	#0, joy_previous

	jsr	BIOS_LOAD_DEFAULT_VDP_REGS
	jsr	BIOS_CLEAR_VRAM
	/* Do not call BIOS_CLEAR_COMM here: the resident Sub launcher has already
	   published STAT_MENU_READY, and this menu only needs its own command
	   latches cleared on boot and on a return from a movie. */
	clr.w	(GA_COMCMD0).l
	clr.w	(GA_COMCMD1).l
	move.w	#0x8C81, (VDP_CTRL).l		/* H40 */
	move.w	#0x9001, (VDP_CTRL).l		/* 64x32 name table */
	move.w	#0x8F02, (VDP_CTRL).l		/* autoincrement 2 */
	move.w	#0x8238, (VDP_CTRL).l		/* Plane A = 0xE000 */
	move.w	#0x8407, (VDP_CTRL).l		/* Plane B also points at the clear map */
	move.w	#0x8174, (VDP_CTRL).l		/* display + DMA */
	bsr	load_menu_palette
	bsr	clear_screen
	bsr	load_menu_font
	jsr	BIOS_VDP_DISP_ENABLE
	bsr	init_controller

/* The Sub launcher owns the CD and prepares both copies of MENUIP.BIN before
   the first menu frame is shown. */
wait_menu_ready:
	cmp.w	#STAT_MENU_READY, (GA_COMSTAT0).l
	bne	wait_menu_ready
	bsr	render_menu
	bsr	wait_controller_release

menu_loop:
	bsr	wait_vblank
	bsr	read_controller_event		/* d0 = newly pressed buttons */
	tst.w	d0
	beq	menu_loop
	btst	#0, d0
	bne	menu_up
	btst	#1, d0
	bne	menu_down
	btst	#6, d0
	bne	menu_play
	btst	#5, d0
	bne	menu_loop_mode
	bra	menu_loop

menu_up:
	move.w	selected, d0
	tst.w	d0
	bne.s	1f
	move.w	#MENU_COUNT-1, selected
	bra.s	2f
1:
	subq.w	#1, d0
	move.w	d0, selected
2:
	bsr	adjust_viewport
	bsr	render_menu
	bra	menu_loop

menu_down:
	move.w	selected, d0
	addq.w	#1, d0
	cmp.w	#MENU_COUNT, d0
blo.s	1f
	moveq	#0, d0
1:
	move.w	d0, selected
	bsr	adjust_viewport
	bsr	render_menu
	bra	menu_loop

menu_play:
	clr.w	(MULTI_LOOP_FLAG_MAIN).l
	bra	launch_selected

menu_loop_mode:
	move.w	#1, (MULTI_LOOP_FLAG_MAIN).l
	bra	launch_selected

/* Keep the selected row inside the nine-line viewport. */
adjust_viewport:
	move.w	#0, viewport_start
	move.w	selected, d0
	cmp.w	#9, d0
	blo.s	1f
	move.w	d0, d1
	subq.w	#8, d1
	move.w	d1, viewport_start
1:
	rts

/* Tell the Sub which item to load.  Bit 15 means C-loop; low 15 bits are the
   manifest index.  The selected player's exact IP byte count comes from the
   generated menu table, not from a guessed fixed size. */
launch_selected:
	move.w	selected, d0
	move.w	d0, d1
	tst.w	(MULTI_LOOP_FLAG_MAIN).l
	beq.s	1f
	ori.w	#0x8000, d1
1:
	move.w	d1, (GA_COMCMD1).l
	move.w	#CMD_MENU_LOAD, (GA_COMCMD0).l
2:
	cmp.w	#STAT_MENU_IP_READY, (GA_COMSTAT0).l
	bne	2b
	/* d0 = selected index * 2, d1 = exact IP byte count. */
	add.w	d0, d0
	lea	menu_ip_sizes, a0
	move.w	(a0,d0.w), d1
	/* Main sees the Sub-loaded staging bank at PROBE_BANK. */
	lea	(PROBE_BANK+PLAYER_IP_STAGE_OFF).l, a0
	lea	PLAYER_ENTRY.l, a1
	move.w	d1, d2
	lsr.w	#1, d2
	beq.s	4f
	subq.w	#1, d2
3:
	move.w	(a0)+, (a1)+
	dbra	d2, 3b
4:
	clr.w	(GA_COMCMD0).l			/* acknowledge the Word-RAM copy */
5:
	cmp.w	#STAT_PLAYER_READY, (GA_COMSTAT0).l
	bne	5b
	movea.l	#PLAYER_ENTRY, a0
	jmp	(a0)

/* --- Input --- */
init_controller:
	move.b	#0x40, (JOY_CTRL).l		/* TH is an output */
	move.b	#0x40, (JOY_DATA).l
	rts

read_controller_event:
	moveq	#0, d0
	move.b	(JOY_DATA).l, d0		/* TH high: directions, B, C */
	not.b	d0
	andi.w	#0x003F, d0
	move.w	d0, d2
	move.b	#0x00, (JOY_DATA).l		/* TH low: directions, A, Start */
	nop
	moveq	#0, d1
	move.b	(JOY_DATA).l, d1
	not.b	d1
	andi.w	#0x0030, d1
	lsl.w	#2, d1				/* A/Start become bits 6/7 */
	move.b	#0x40, (JOY_DATA).l
	or.w	d1, d2
	move.w	d2, d0
	move.w	joy_previous, d1
	move.w	d2, joy_previous
	not.w	d1
	and.w	d1, d0
	rts

wait_controller_release:
1:
	bsr	read_controller_event
	tst.w	d0
	bne	1b
	move.w	joy_previous, d0
	tst.w	d0
	bne	1b
	rts

/* --- VDP and menu drawing --- */
load_menu_palette:
	move.l	#0xC0000000, (VDP_CTRL).l
	lea	menu_palette, a0
	move.w	#64-1, d0
1:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d0, 1b
	rts

load_menu_font:
	move.l	#0x40200000, (VDP_CTRL).l		/* tile 1 */
	lea	menu_font, a0
	move.w	#(MENU_FONT_BYTES/2)-1, d0
1:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d0, 1b
	rts

clear_screen:
	moveq	#0, d0
	moveq	#0, d1
	moveq	#28-1, d2
1:
	bsr	clear_row
	addq.w	#1, d0
	dbra	d2, 1b
	rts

/* d0=row, d1=palette attribute */
clear_row:
	movem.l	d0-d3, -(sp)
	move.w	d0, d2
	lsl.w	#7, d2
	add.w	#MENU_MAP, d2
	move.w	d2, d0
	bsr	set_vram_write
	move.w	d1, d3
	moveq	#40-1, d2
1:
	move.w	d3, (VDP_DATA).l
	dbra	d2, 1b
	movem.l	(sp)+, d0-d3
	rts

/* a0=zero-terminated ASCII, d0=x, d1=y, d2=palette attribute */
write_string:
	movem.l	d0-d5/a0, -(sp)
	move.w	d0, d3
	add.w	d3, d3
	move.w	d1, d4
	lsl.w	#7, d4
	add.w	d3, d4
	add.w	#MENU_MAP, d4
	move.w	d4, d0
	bsr	set_vram_write
	move.w	d2, d5
1:
	moveq	#0, d3
	move.b	(a0)+, d3
	beq.s	2f
	subi.w	#32, d3
	addq.w	#1, d3				/* font tile 1 is ASCII space */
	or.w	d5, d3
	move.w	d3, (VDP_DATA).l
	bra.s	1b
2:
	movem.l	(sp)+, d0-d5/a0
	rts

/* Render one complete menu only after a selection change or return from a
   movie.  This keeps the steady menu loop to one pad sample per VBlank. */
render_menu:
	movem.l	d0-d7/a0-a6, -(sp)
	bsr	clear_screen
	lea	menu_title, a0
	moveq	#1, d0
	moveq	#0, d1
	moveq	#0, d2
	bsr	write_string
	lea	menu_subtitle, a0
	moveq	#1, d0
	moveq	#1, d1
	moveq	#0, d2
	bsr	write_string
	lea	menu_separator, a0
	moveq	#0, d0
	moveq	#2, d1
	moveq	#0, d2
	bsr	write_string

	moveq	#0, d7				/* viewport slot */
menu_rows:
	move.w	viewport_start, d6
	add.w	d7, d6
	cmp.w	#MENU_COUNT, d6
	bhs.s	menu_rows_done
	moveq	#0, d5
	cmp.w	selected, d6
	bne.s	1f
	move.w	#MENU_PALETTE_ATTR, d5
1:
	move.w	d7, d0
	addq.w	#3, d0				/* row */
	move.w	d5, d1
	bsr	clear_row
	/* cursor marker at column 2 */
	moveq	#2, d0
	move.w	d7, d1
	addq.w	#3, d1
	move.w	d5, d2
	cmp.w	selected, d6
	bne.s	2f
	lea	cursor_mark, a0
	bra.s	3f
2:
	lea	blank_mark, a0
3:
	bsr	write_string
	/* menu_list_ptrs[index] */
	move.w	d6, d0
	lsl.w	#2, d0
	lea	menu_list_ptrs, a0
	movea.l	(a0,d0.w), a0
	moveq	#4, d0
	move.w	d7, d1
	addq.w	#3, d1
	move.w	d5, d2
	bsr	write_string
	addq.w	#1, d7
	cmp.w	#9, d7
	blo	menu_rows
menu_rows_done:
	/* Scroll arrows occupy the far right edge of the viewport. */
	move.w	viewport_start, d0
	beq.s	4f
	lea	arrow_up, a0
	moveq	#37, d0
	moveq	#3, d1
	moveq	#0, d2
	bsr	write_string
4:
	move.w	viewport_start, d0
	addi.w	#9, d0
	cmp.w	#MENU_COUNT, d0
	bhs.s	5f
	lea	arrow_down, a0
	moveq	#37, d0
	moveq	#11, d1
	moveq	#0, d2
	bsr	write_string
5:
	lea	menu_separator, a0
	moveq	#0, d0
	moveq	#12, d1
	moveq	#0, d2
	bsr	write_string
	/* Details for the selected row. */
	move.w	selected, d0
	lsl.w	#2, d0
	lea	menu_detail_title_ptrs, a0
	movea.l	(a0,d0.w), a0
	moveq	#1, d0
	moveq	#13, d1
	moveq	#0, d2
	bsr	write_string
	move.w	selected, d0
	lsl.w	#2, d0
	lea	menu_detail_specs_ptrs, a0
	movea.l	(a0,d0.w), a0
	moveq	#1, d0
	moveq	#14, d1
	moveq	#0, d2
	bsr	write_string
	move.w	selected, d0
	lsl.w	#2, d0
	lea	menu_detail_timing_ptrs, a0
	movea.l	(a0,d0.w), a0
	moveq	#1, d0
	moveq	#15, d1
	moveq	#0, d2
	bsr	write_string
	lea	menu_controls_0, a0
	moveq	#1, d0
	moveq	#20, d1
	moveq	#0, d2
	bsr	write_string
	lea	menu_controls_1, a0
	moveq	#1, d0
	moveq	#21, d1
	moveq	#0, d2
	bsr	write_string
	lea	menu_controls_2, a0
	moveq	#1, d0
	moveq	#22, d1
	moveq	#0, d2
	bsr	write_string
	lea	menu_separator, a0
	moveq	#0, d0
	moveq	#24, d1
	moveq	#0, d2
	bsr	write_string
	movem.l	(sp)+, d0-d7/a0-a6
	rts

set_vram_write:
	and.l	#0x0000FFFF, d0
	lsl.l	#2, d0
	lsr.w	#2, d0
	swap	d0
	or.l	#0x40000000, d0
	move.l	d0, (VDP_CTRL).l
	rts

wait_vblank:
1:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq.s	1b
2:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	bne.s	2b
	rts

	.data
	.align	2
menu_palette:
	/* palette 0: black/white, palette 1: yellow/black, palette 2/3 accents */
	.word	0x0000,0x0EEE,0,0,0,0,0,0,0,0,0,0,0,0,0,0
	.word	0x00AE,0x0000,0,0,0,0,0,0,0,0,0,0,0,0,0,0
	.word	0x0000,0x00EE,0,0,0,0,0,0,0,0,0,0,0,0,0,0
	.word	0x0000,0x0E00,0,0,0,0,0,0,0,0,0,0,0,0,0,0

	.align	2
menu_font:
	.incbin	"menu_font.bin"

	.align	2
menu_separator:
	.ascii	"----------------------------------------"
	.byte	0
cursor_mark:
	.byte	'>',0
blank_mark:
	.byte	' ',0
arrow_up:
	.byte	'^',0
arrow_down:
	.byte	'v',0
menu_controls_0:
	.asciz	"UP/DOWN SELECT   A PLAY   C LOOP"
menu_controls_1:
	.asciz	"A returns to this menu after playback"
menu_controls_2:
	.asciz	"C loops until RESET"

	.bss
	.align	2
selected:
	.word	0
viewport_start:
	.word	0
joy_previous:
	.word	0
