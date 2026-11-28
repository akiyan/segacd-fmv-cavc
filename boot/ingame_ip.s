/*
 * In-game CAVC player, Main CPU module.
 *
 * A host game loads this image at its link base (INGAME_MAIN_BASE) and calls
 * the entry once per movie, after its Sub program has started the in-game
 * Sub module (movieplay_sp.s built with INGAME) and after stopping its own
 * music, unless flag bit 1 keeps the host's level-4 horizontal interrupt
 * (for example a music driver) running during the movie. Otherwise the movie
 * owns the interrupts for the duration of the call: it masks the horizontal
 * interrupt and disables it in VDP register 0. Either way it replaces the
 * level-6 vertical-interrupt target with its own handler, which performs every
 * VDP write of the movie inside the vertical blank. The host's interrupt mask,
 * register 0 and level-6 target are restored on return. A kept horizontal
 * interrupt must not touch the VDP or the comm registers the movie owns, and
 * its work must end before the vertical blank: the hook preempts it there.
 * PLAYER.md (In-game player) owns the memory map and the calling contract.
 *
 * Entry: a0 -> parameters (VDP register values as register-write words,
 * for example 0x8174 for register 1)
 *   +0  .w  VRAM address of the movie's 64x32 name table (0x2000 aligned)
 *   +2  .w  VRAM address of the host's horizontal-scroll table
 *   +4  .w  host VDP register 0 (always restored)
 *   +6  .w  host VDP register 1     \
 *   +8  .w  host VDP register 2      | restored when flag bit 0 is set;
 *   +10 .w  host VDP register 4      | otherwise the last frame stays up
 *   +12 .w  host VDP register 7     /
 *   +14 .l  address of the level-6 jump-table long (BIOS: 0xFFFD08)
 *   +18 .w  flags: bit 0 = restore registers 1/2/4/7 before returning,
 *               bit 1 = keep the host's horizontal interrupt enabled
 * Return: d0.w status (0 = played, 0xBAD1 = the Sub refused the stream),
 *   d1.l frames published, d2.w frames published after their deadline,
 *   d3.w largest lateness in VBlanks, d4.w Sub slip recoveries,
 *   d5.w control desynchronizations. d6-d7/a0-a6 are preserved.
 */
	.include "player_constants.inc"

.if PC_INGAME != 1
.error "the in-game Main module needs in-game player constants"
.endif
.if PC_CADENCE_PERIOD != 1
.error "the in-game Main module supports a fixed VBlank cadence only"
.endif
.if (PC_FEATURES & 0x0200)
.error "the in-game Main module does not play scroll windows"
.endif
.if PC_DIC_PATTERNS != 0
.error "the in-game Main module has no DicBuf"
.endif
.if (PC_TCOLS & 7) || (PC_TCOLS > 40) || (PC_TROWS > 28)
.error "the in-game Main module needs whole bitmap bytes per name-table row"
.endif

/* Diagnostic build options (never in a game build):
   IDLE_PROFILE   counts the scanlines Main spends in the playback wait loops,
                  split into active-display and VBlank lines, and writes them
                  at each VBlank hook entry to VSRAM 0x40/0x42 with the
                  preceding hook's exit V counter at 0x44, where a BlastEm VDP
                  trace records them (harness/ingame_player).
   SUBBUS_LOAD=N  with IDLE_PROFILE: at the end of every hook, holds the Sub
                  CPU's bus for about N Main cycles and reads PRG-RAM through
                  the Main window, like a music driver fetching song data. */
.equ VDP_DATA, 0x00C00000
.equ VDP_CTRL, 0x00C00004
.equ VDP_HV, 0x00C00008
.equ GA_SUB_CTRL, 0x00A12001
.equ GA_MEMMODE, 0x00A12002
.equ GA_COMCMD0, 0x00A12010
.equ GA_COMCMD1, 0x00A12012
.equ GA_COMSTAT0, 0x00A12020

.equ CMD_STREAM, 0x50
.equ CMD_SWAP,   0x51
.equ STAT_BOOT_STAGE, 0x8001
.equ STAT_READY, 0x8003
.equ STAT_END,   0x8004
.equ STAT_F0_CHUNK, 0x8005
.equ STAT_FAIL,  0x80FF

/* The Main view of the owned 1M bank. The movie uses its top only. */
.equ WORD_BANK, 0x00200000
.equ OUT_BASE, WORD_BANK+PC_BANK_BASE
.equ O_NRUN, OUT_BASE+0
.equ O_NLOAD, OUT_BASE+2
.equ O_LOADS, OUT_BASE+4
.equ CTRL_SCR, WORD_BANK+PC_CTRL_SCR_OFFSET
.equ O_STATUS, WORD_BANK+PC_STATUS_OFFSET
.equ O_SLIP, O_STATUS+0x00
.equ O_DSY, O_STATUS+0x7E
.equ BOOT_STAGE, OUT_BASE
.equ BOOT_VRAM_DIR, BOOT_STAGE+0x0FC0
.equ BOOT_VRAM_MAGIC, 0x4256524D		/* "BVRM" */
.equ WR0_LIMIT, WORD_BANK+PC_WR0_OFFSET	/* inline Prg payload ends here */
.equ WR1_LIMIT, WORD_BANK+PC_WR1_OFFSET

/* Each shadow is the movie's name-table band with the 64-entry plane pitch,
   so one DMA publishes it; the off-screen columns stay zero. */
.equ NT_BAND_WORDS, (PC_TROWS-1)*64+PC_TCOLS
.equ SHADOW_BYTES, NT_BAND_WORDS*2
.equ ROW_GAP_BYTES, (64-PC_TCOLS)*2
.equ ROW_BM_BYTES, PC_TCOLS/8
.equ FINAL_SLOT, PC_POOL-12			/* final-only slots end the pool */
.equ FINAL_DST, (FINAL_SLOT+1)*32		/* their first VRAM byte */
.equ FINAL_MAX_PATTERNS, 12
.equ FINAL_MAX_RUNS, 12

/* The blank is measured, not estimated: the hook reads the gate array's
   stopwatch (30.72 us per tick) on entry, and before each DMA tick_words
   gives the DMA words that still end inside the blank. The 38-line NTSC
   blank is 78.6 ticks, but the hook starts after the interrupt entry and
   BlastEm ends full-speed blank DMA about 36 lines after it, so the budget
   stops at 72 ticks (34.8 lines). An H40 blank line moves about 102 words,
   49.5 per tick; the table uses 48 and keeps one tick for the work after
   the last DMA. CALC_SETUP_WORDS is the
   CPU time, in DMA words, of a transfer whose registers are computed here. */
.equ GA_STOPWATCH, 0x00A1200C
.equ VB_BUDGET_TICKS, 72
.equ WORDS_PER_TICK, 48
.equ CALC_SETUP_WORDS, 80
/* Records are admitted against a running estimate (their words plus
   REC_SETUP_WORDS, above the measured CPU time of about 70 words around a
   prebuilt record) and the stopwatch is read again only when the estimate
   runs out, so most records skip the measurement. */
.equ REC_SETUP_WORDS, 80
.equ NT_COST, NT_BAND_WORDS+CALC_SETUP_WORDS
.equ CRAM_COST, 64+CALC_SETUP_WORDS
.equ SIDECAR_PER_VBLANK, 32

.equ FRAME_TYPE_MASK, 0x6000
.equ LIST_BIT, 15
.equ COUNT_MASK, 0x1FFF

/* VBlank jobs that run before playback. */
.equ JOB_NONE, 0
.equ JOB_BLANK, 1			/* frame -1: blank CRAM and name table */
.equ JOB_SIDECAR, 2			/* boot-stage direct VRAM records */

.macro IDLE_POLL
.ifdef IDLE_PROFILE
	bsr	idle_tick
.endif
.endm

	.text
module_header:
	.ascii	"CAVM"
	.word	1				/* interface version */
	.word	0
	.long	module_header			/* link base = required load address */
	.long	image_end-module_header		/* bytes to load */
	.long	bss_end-module_header		/* bytes of Main RAM used */
	.long	ingame_main

ingame_main:
	movem.l	d6-d7/a0-a6, -(sp)
	/* Zero the state and copy the parameters. */
	lea	bss_start, a1
	move.w	#(bss_end-bss_start)/2-1, d0
1:
	clr.w	(a1)+
	dbra	d0, 1b
	move.w	(a0)+, p_nt
	move.w	(a0)+, p_hscroll
	move.w	(a0)+, p_reg0
	move.w	(a0)+, p_reg1
	move.w	(a0)+, p_reg2
	move.w	(a0)+, p_reg4
	move.w	(a0)+, p_reg7
	move.l	(a0)+, p_vint_slot
	move.w	(a0)+, p_flags
	move.l	#-1, published
	move.l	#-1, rec_done
	/* row_gap[b] = pitch bytes above bitmap byte b's row */
	lea	row_gap, a1
	moveq	#0, d1
	moveq	#0, d2
	move.w	#PC_BMBYTES-1, d0
1:
	move.w	d1, (a1)+
	addq.w	#1, d2
	cmpi.w	#ROW_BM_BYTES, d2
	bne.s	2f
	moveq	#0, d2
	addi.w	#ROW_GAP_BYTES, d1
2:
	dbra	d0, 1b
	lea	palidx_image, a0
	move.l	a0, palidx_ptr
	/* Own the interrupts: only the movie's vertical interrupt is taken,
	   and the host's horizontal interrupt when flag bit 1 keeps it. */
	move.w	sr, host_sr
	move.w	#0x2500, sr
	btst	#1, p_flags+1
	beq.s	1f
	move.w	#0x2300, sr
1:
	movea.l	p_vint_slot, a1
	move.l	(a1), host_vint
	move.l	#vint_hook, (a1)
	/* Frame -1: a black display while patterns are loaded. */
	move.w	#JOB_BLANK, vjob
1:
	tst.w	vjob
	bne.s	1b

	move.w	#CMD_STREAM, (GA_COMCMD0).l
boot_wait:
	move.w	(GA_COMSTAT0).l, d0
	cmpi.w	#STAT_BOOT_STAGE, d0
	beq	boot_stage
	cmpi.w	#STAT_F0_CHUNK, d0
	beq	boot_chunk
	cmpi.w	#STAT_READY, d0
	beq	boot_frame0
	cmpi.w	#STAT_FAIL, d0
	beq	boot_failed
	bra.s	boot_wait

boot_stage:
	/* Copy the optional boot-VRAM sidecar records in VBlanks. */
	lea	BOOT_VRAM_DIR, a0
	cmpi.l	#BOOT_VRAM_MAGIC, (a0)
	bne.s	2f
	lea	sc_counts, a1
	move.w	4(a0), (a1)+
	move.w	6(a0), (a1)+
	move.w	8(a0), (a1)+
	clr.w	sc_region
	move.l	#BOOT_STAGE, sc_ptr
	move.w	sc_counts, sc_left
	move.w	#JOB_SIDECAR, vjob
1:
	tst.w	vjob
	bne.s	1b
2:
	bsr	ack_stage
	bra	boot_wait

boot_chunk:
	/* One frame-0 O_LOADS chunk: transfer it, then give the bank back. */
	moveq	#0, d0
	move.l	#WR0_LIMIT, d1
	bsr	start_records
1:
	tst.w	rec_go
	bne.s	1b
	bsr	ack_stage
	bra	boot_wait

boot_frame0:
	/* The last chunk arrives with frame 0's control. */
	moveq	#0, d7
	lea	shadow0, a2
	bsr	apply_control
	lea	paltab_image, a0
	move.l	a0, cram_ptr0
	bsr	read_sub_status
	moveq	#0, d0
	bsr	arm_frame
	moveq	#0, d0
	move.l	#WR0_LIMIT, d1
	bsr	start_records
	moveq	#0, d0
	bsr	arm_publication
1:
	tst.l	published
	bmi.s	1b
	/* Frame 0 is visible: launch the timed read with the original command.
	   Sub clears READY once frame 1's physical slot has arrived. */
	move.w	#0, (GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	bne.s	1b
	moveq	#1, d7				/* next frame */

frame_loop:
	/* The previous frame's records are done, so its bank can go back. */
1:
	IDLE_POLL
	tst.w	rec_go
	bne.s	1b
	move.w	#CMD_SWAP, (GA_COMCMD0).l
1:
	IDLE_POLL
	move.w	(GA_COMSTAT0).l, d0
	cmpi.w	#STAT_READY, d0
	beq.s	2f
	cmpi.w	#STAT_END, d0
	beq	movie_end
	bra.s	1b
2:
	move.w	#0, (GA_COMCMD0).l
1:
	IDLE_POLL
	tst.w	(GA_COMSTAT0).l
	bne.s	1b
	/* Build frame d7 in its parity's shadow from the preceding frame. That
	   buffer was last published two frames ago, before the preceding
	   frame's records could start. */
	move.l	d7, d0
	subq.l	#1, d0
	bsr	slot_shadow
	movea.l	a2, a0				/* preceding frame */
	move.l	d7, d0
	bsr	slot_shadow			/* a2 = this frame's shadow */
	movea.l	a2, a3
	move.w	#SHADOW_BYTES/4-1, d0
1:
	move.l	(a0)+, (a3)+
	dbra	d0, 1b
	.if SHADOW_BYTES & 2
	move.w	(a0)+, (a3)+
	.endif
	move.l	d7, d0
	bsr	slot_cram_clear
	bsr	apply_control
	bsr	palette_switch
	bsr	read_sub_status
	move.l	d7, d0
	bsr	arm_frame
	move.l	d7, d0
	move.l	#WR0_LIMIT, d1
	btst	#0, d7
	beq.s	1f
	move.l	#WR1_LIMIT, d1
1:
	bsr	start_records
	move.l	d7, d0
	bsr	arm_publication
	addq.l	#1, d7
	bra	frame_loop

movie_end:
	move.w	#0, (GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	bne.s	1b
	/* Hold until the final frame is visible. */
	subq.l	#1, d7
1:
	IDLE_POLL
	cmp.l	published, d7
	bne.s	1b
	moveq	#0, d6				/* status */
	bra.s	finish

boot_failed:
	move.w	#0, (GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	bne.s	1b
	move.w	#0xBAD1, d6

finish:
	/* Sub returns Word RAM in 2M mode with Main as its owner. */
1:
	move.b	(GA_MEMMODE+1).l, d0
	andi.b	#0x05, d0			/* MODE, RET */
	cmpi.b	#0x01, d0
	bne.s	1b
	bsr	wait_vblank_task
	lea	VDP_CTRL, a6
	move.w	p_reg0, (a6)			/* the host's H-int setting */
	btst	#0, p_flags+1
	beq.s	2f
	move.w	p_reg2, (a6)
	move.w	p_reg4, (a6)
	move.w	p_reg7, (a6)
	move.w	p_reg1, (a6)
2:
	movea.l	p_vint_slot, a1
	move.l	host_vint, (a1)
	move.w	host_sr, sr
	move.w	d6, d0
	move.l	published, d1
	addq.l	#1, d1
	move.w	late_frames, d2
	move.w	max_late, d3
	move.w	sub_slips, d4
	move.w	sub_desyncs, d5
	movem.l	(sp)+, d6-d7/a0-a6
	rts

/* Acknowledge a boot-stage or frame-0 chunk handoff and wait for Sub to take
   the bank back. */
ack_stage:
	move.w	#1, (GA_COMCMD1).l
1:
	tst.w	(GA_COMSTAT0).l
	bne.s	1b
	move.w	#0, (GA_COMCMD1).l
	rts

/* Wait for the start of the next vertical blank from task level. */
wait_vblank_task:
	move.w	vb_count, d0
1:
	cmp.w	vb_count, d0
	beq.s	1b
	rts

/* d0.l = frame -> a2 = its parity's shadow. */
slot_shadow:
	lea	shadow0, a2
	btst	#0, d0
	beq.s	1f
	lea	shadow1, a2
1:
	rts

/* d0.l = frame: no CRAM change unless control or PALIDX supplies one. */
slot_cram_clear:
	btst	#0, d0
	bne.s	1f
	clr.l	cram_ptr0
	rts
1:
	clr.l	cram_ptr1
	rts

/* Apply the owned bank's control to the shadow at a2. A fade copies its
   inline CRAM image to the frame's fade buffer. d7 = frame. */
apply_control:
	movem.l	d0-d6/a0-a3, -(sp)
	lea	(CTRL_SCR+4).l, a0
	move.w	(a0)+, d5			/* list bit, type, count */
	move.w	d5, d6
	andi.w	#FRAME_TYPE_MASK, d6
	cmpi.w	#FRAME_TYPE_MASK, d6
	beq	ac_done				/* scroll controls are not supported */
	tst.w	d6
	beq.s	1f
	lea	fade0, a1
	lea	cram_ptr0, a3
	btst	#0, d7
	beq.s	2f
	lea	fade1, a1
	lea	cram_ptr1, a3
2:
	move.l	a1, (a3)
	moveq	#16-1, d0
3:
	move.l	(a0)+, (a1)+
	move.l	(a0)+, (a1)+
	dbra	d0, 3b
1:
	move.w	d5, d4
	andi.w	#COUNT_MASK, d4
	beq	ac_done
	cmpi.w	#PC_CELLS, d4
	bls.s	1f
	move.w	#PC_CELLS, d4
1:
	btst	#LIST_BIT, d5
	bne	ac_list
	/* Bitmap: one bit per cell, LSB first, then one entry per set bit. Each
	   name-table row is a whole number of bitmap bytes. */
	movea.l	a0, a1				/* bitmap */
	adda.w	#((PC_BMBYTES+1)&0xFFFE), a0	/* entries */
	move.w	#PC_BMBYTES-1, d5
	moveq	#ROW_BM_BYTES, d6		/* bytes left in this row */
ac_byte:
	move.b	(a1)+, d0
	beq.s	ac_zero
	cmpi.b	#0xFF, d0
	beq.s	ac_full
	moveq	#7, d1
ac_bit:
	lsr.b	#1, d0
	bcc.s	1f
	move.w	(a0)+, d3
	andi.w	#0x67FF, d3			/* strip cold and source bits */
	move.w	d3, (a2)
1:
	addq.l	#2, a2
	dbra	d1, ac_bit
	bra.s	ac_next
ac_zero:
	lea	16(a2), a2
	bra.s	ac_next
ac_full:
	.rept 8
	move.w	(a0)+, d3
	andi.w	#0x67FF, d3
	move.w	d3, (a2)+
	.endr
ac_next:
	subq.w	#1, d6
	bne.s	1f
	lea	ROW_GAP_BYTES(a2), a2		/* next name-table row */
	moveq	#ROW_BM_BYTES, d6
1:
	dbra	d5, ac_byte
	bra.s	ac_done
ac_list:
	/* Items address the logical cell (offset = cell*2); row_gap adds the
	   pitch of the rows above it. */
	lea	row_gap, a3
	subq.w	#1, d4
1:
	move.w	(a0)+, d0			/* logical byte offset */
	move.w	(a0)+, d1			/* final name entry */
	cmpi.w	#PC_CELLS*2, d0
	bhs.s	2f
	move.w	d0, d2
	lsr.w	#4, d2				/* bitmap byte = cell/8 */
	add.w	d2, d2
	add.w	(a3,d2.w), d0
	move.w	d1, (a2,d0.w)
2:
	dbra	d4, 1b
ac_done:
	movem.l	(sp)+, d0-d6/a0-a3
	rts

/* PALIDX: a segment switch at frame d7 reloads CRAM from PALTAB. */
palette_switch:
	movea.l	palidx_ptr, a0
	tst.w	2(a0)
	beq.s	1f				/* (0xFFFF, 0) terminator */
	move.w	(a0), d0
	cmp.w	d7, d0
	bhi.s	1f
	move.w	2(a0), d0
	andi.w	#0x003F, d0
	lsl.w	#7, d0
	lea	paltab_image, a1
	adda.w	d0, a1
	lea	cram_ptr0, a2
	btst	#0, d7
	beq.s	2f
	lea	cram_ptr1, a2
2:
	move.l	a1, (a2)
	addq.l	#4, a0
	move.l	a0, palidx_ptr
1:
	rts

read_sub_status:
	move.w	(O_SLIP).l, sub_slips
	move.w	(O_DSY).l, sub_desyncs
.ifdef IDLE_PROFILE
	/* A DEBUG Sub module's per-frame diagnostics (zero otherwise). */
	move.w	(O_STATUS+0x2C).l, sub_diag+0	/* last slip: expected sector */
	move.w	(O_STATUS+0x2E).l, sub_diag+2	/* received */
	move.w	(O_STATUS+0x30).l, sub_diag+4	/* its frame slot */
	move.w	(O_STATUS+0x32).l, sub_diag+6	/* its sector in the slot */
.endif
	rts

/* Prepare frame d0.l's publication: copy its final-only patterns out of
   Word RAM and record the VBlank cost. The VBlank hook publishes it once
   its records are done, its deadline has come and the cost fits. */
arm_frame:
	movem.l	d0-d7/a0-a5, -(sp)
	move.l	d0, d7
	lea	fin0, a2			/* run table */
	lea	finbuf0, a3			/* pattern copies */
	lea	pub0, a4			/* per-slot publication words */
	btst	#0, d7
	beq.s	1f
	lea	fin1, a2
	lea	finbuf1, a3
	lea	pub1, a4
1:
	moveq	#0, d5				/* final runs */
	move.w	#NT_COST, d6		/* publication cost in DMA words */
	lea	O_LOADS, a0
	move.w	(O_NRUN).l, d4
	move.l	#WR0_LIMIT, d3
	btst	#0, d7
	beq.s	1f
	move.l	#WR1_LIMIT, d3
1:
	tst.w	d4
	beq.s	af_done
	subq.w	#1, d4
af_rec:
	movea.l	a0, a5				/* this record */
	move.w	(a5), d1			/* words */
	movea.l	18(a5), a1			/* raw source */
	lea	22(a5), a0			/* next record unless Prg */
	cmpa.l	d3, a1
	bhs.s	1f
	movea.l	a1, a0				/* Prg payload follows the record */
	adda.w	d1, a0
	adda.w	d1, a0
1:
	move.w	10(a5), d0			/* raw destination */
	cmpi.w	#FINAL_DST, d0
	blo.s	af_next
	cmpi.w	#FINAL_MAX_RUNS, d5
	bhs.s	af_next				/* bounded by the encoder */
	move.w	d0, (a2)+			/* destination */
	move.w	d1, (a2)+			/* words */
	move.l	a3, (a2)+			/* Main-RAM copy */
	add.w	d1, d6
	addi.w	#CALC_SETUP_WORDS, d6
	addq.w	#1, d5
	subq.w	#1, d1
3:
	move.w	(a1)+, (a3)+
	dbra	d1, 3b
af_next:
	dbra	d4, af_rec
af_done:
	move.l	cram_ptr0, d0
	btst	#0, d7
	beq.s	1f
	move.l	cram_ptr1, d0
1:
	tst.l	d0
	beq.s	1f
	addi.w	#CRAM_COST, d6
1:
	move.w	d5, 0(a4)			/* final runs */
	move.w	d6, 2(a4)			/* cost */
	movem.l	(sp)+, d0-d7/a0-a5
	rts

/* Allow frame d0.l's publication. Called after start_records, so the hook
   can never see it armed while its records are not yet running. */
arm_publication:
	move.l	a4, -(sp)
	lea	pub0, a4
	btst	#0, d0
	beq.s	1f
	lea	pub1, a4
1:
	move.w	#1, 4(a4)
	movea.l	(sp)+, a4
	rts

/* Hand frame d0.l's records (d1 = inline-payload limit) to the hook. */
start_records:
	move.l	d0, rec_frame
	subq.l	#1, d0
	move.l	d0, rec_done			/* not yet done */
	move.l	d1, rec_limit
	move.l	#O_LOADS, rec_ptr
	move.w	(O_NRUN).l, rec_left
	move.w	#1, rec_go
	rts

/* ------------------------------------------------------------------ */
/* Vertical-interrupt hook. All VDP access of the movie happens here.   */
vint_hook:
	movem.l	d0-d7/a0-a6, -(sp)
	move.w	(GA_STOPWATCH).l, vb_tick0
	addq.w	#1, vb_count
	lea	VDP_CTRL, a6
	lea	VDP_DATA, a5
	move.w	#0x8F02, (a6)			/* autoincrement 2 */
.ifdef IDLE_PROFILE
	move.l	#0x40400010, (a6)		/* VSRAM 0x40: the interval that ended */
	move.w	idle_blank, (a5)
	move.w	idle_active, (a5)
	move.w	hook_exit_v, (a5)
	move.w	sub_slips, (a5)			/* 0x46.. Sub diagnostics */
	move.w	sub_diag+0, (a5)
	move.w	sub_diag+2, (a5)
	move.w	sub_diag+4, (a5)
	move.w	sub_diag+6, (a5)
	clr.w	idle_blank
	clr.w	idle_active
.endif
	move.w	vjob, d0
	beq.s	vh_play
	cmpi.w	#JOB_BLANK, d0
	bne.s	1f
	bsr	job_blank
	bra	vh_done
1:
	bsr	job_sidecar
	bra	vh_done
vh_play:
	/* Records first, with the whole blank: a frame cannot be published
	   before its records are done, so holding units back for its
	   publication would only delay it. */
	tst.w	rec_go
	beq.s	vh_publish
	bsr	records_step
vh_publish:
	bsr	pub_slot
	tst.w	4(a4)
	beq.s	vh_done				/* not armed */
	tst.w	rec_go
	beq.s	1f
	cmp.l	rec_frame, d6
	beq.s	vh_done				/* its records are still running */
1:
	bsr	pub_due
	bne.s	vh_done
	bsr	words_left
	cmp.w	2(a4), d0
	blo.s	vh_done				/* not enough of this blank left */
	bsr	publish
	/* The following frame's records may start in the same blank. */
	tst.w	rec_go
	beq.s	vh_done
	bsr	records_step
vh_done:
.ifdef IDLE_PROFILE
.ifdef SUBBUS_LOAD
	/* A music driver's fetch: hold the Sub bus and read PRG-RAM. */
	bset	#1, (GA_SUB_CTRL).l
1:
	btst	#1, (GA_SUB_CTRL).l
	beq.s	1b
	lea	0x00020000, a0
	move.w	#SUBBUS_LOAD/24-1, d0
1:
	move.w	(a0)+, d1			/* 24 cycles per word */
	dbra	d0, 1b
	bclr	#1, (GA_SUB_CTRL).l
.endif
	moveq	#0, d0
	move.b	(VDP_HV).l, d0
	move.w	d0, hook_exit_v
.endif
	movem.l	(sp)+, d0-d7/a0-a6
	rte

/* a4 = publication words of frame published+1 (in d6). */
pub_slot:
	move.l	published, d6
	addq.l	#1, d6
	lea	pub0, a4
	btst	#0, d6
	beq.s	1f
	lea	pub1, a4
1:
	rts

/* Z set when frame d6 is due in this blank. Frames 0 and 1 are due as soon
   as they are ready; later frames follow frame 1's VBlank cadence. */
pub_due:
	cmpi.l	#1, d6
	bls.s	1f
	move.l	d6, d0
	subq.w	#1, d0
	mulu.w	#PC_VSYNC_N, d0
	add.w	base_vb, d0
	move.w	vb_count, d1
	sub.w	d0, d1
	bmi.s	2f
1:
	moveq	#0, d0				/* Z */
	rts
2:
	moveq	#1, d0				/* NZ */
	rts

.ifdef IDLE_PROFILE
/* Count one idle scanline each time the V counter changes between two polls
   of a wait loop; a VBlank hook in between only resynchronizes. Lines with
   V >= 0xE0 are VBlank lines. Preserves every register and the flags' users
   (it runs before each loop test). */
idle_tick:
	movem.l	d0-d1, -(sp)
	move.w	vb_count, d1
	move.b	(VDP_HV).l, d0
	cmp.w	idle_vb, d1
	bne.s	3f
	cmp.b	idle_v, d0
	beq.s	2f
	move.b	d0, idle_v
	cmpi.b	#0xE0, d0
	bhs.s	1f
	addq.w	#1, idle_active
	bra.s	2f
1:
	addq.w	#1, idle_blank
2:
	movem.l	(sp)+, d0-d1
	rts
3:
	move.w	d1, idle_vb
	move.b	d0, idle_v
	bra.s	2b
.endif

/* d0 = DMA words that still end inside this blank. */
words_left:
	move.w	(GA_STOPWATCH).l, d0
	sub.w	vb_tick0, d0
	andi.w	#0x0FFF, d0
	cmpi.w	#VB_BUDGET_TICKS, d0
	bhs.s	1f
	add.w	d0, d0
	move.w	tick_words(pc,d0.w), d0
	rts
1:
	moveq	#0, d0
	rts
tick_words:
	.set	tick, 0
	.rept	VB_BUDGET_TICKS
	.if	(VB_BUDGET_TICKS-1-tick) > 0
	.word	(VB_BUDGET_TICKS-1-tick)*WORDS_PER_TICK
	.else
	.word	0
	.endif
	.set	tick, tick+1
	.endr

/* Transfer records until done or out of blank. */
records_step:
	move.l	rec_frame, d0
	subq.l	#1, d0
	cmp.l	published, d0
	bgt	rs_ret				/* preceding frame still displayed */
	movea.l	rec_ptr, a0
	move.l	rec_limit, d3
	move.w	rec_left, d6
	bsr	words_left
	move.w	d0, d5				/* estimated words that still fit */
rs_loop:
	tst.w	d6
	beq	rs_finished
	movea.l	a0, a2				/* this record */
	move.w	(a2), d4			/* words, bit 15 = split remainder */
	move.w	d4, d1
	andi.w	#0x7FFF, d1
	movea.l	18(a2), a1			/* raw source */
	lea	22(a2), a0			/* next record unless Prg */
	cmpa.l	d3, a1
	bhs.s	1f
	movea.l	a1, a0				/* Prg: next record follows the payload */
	adda.w	d1, a0
	adda.w	d1, a0
1:
	cmpi.w	#FINAL_DST, 10(a2)
	bhs.s	rs_next				/* final-only: published from Main RAM */
	tst.w	d4
	bmi.s	rs_calc
	move.w	d1, d0
	addi.w	#REC_SETUP_WORDS, d0
	cmp.w	d5, d0
	bls.s	rs_whole
	bsr	words_left			/* the estimate ran out: measure */
	move.w	d0, d5
	move.w	d1, d0
	addi.w	#REC_SETUP_WORDS, d0
	cmp.w	d5, d0
	bhi.s	rs_split
rs_whole:
	sub.w	d0, d5
	/* Whole record with the registers Sub built. */
	move.l	2(a2), (a6)			/* lengths */
	move.l	12(a2), (a6)			/* source low, middle */
	move.w	16(a2), (a6)			/* source high */
	move.l	6(a2), d0
	ori.w	#0x0080, d0			/* CD5: memory-to-VRAM DMA */
	move.l	d0, (a6)
2:
	move.w	(a6), d0
	btst	#1, d0
	bne.s	2b
	move.l	6(a2), (a6)			/* repair the first word */
	move.w	(a1), (a5)
rs_next:
	subq.w	#1, d6
	bra.s	rs_loop
rs_calc:
	/* A split remainder: its registers are computed. */
	bsr	words_left
	move.w	d0, d5
	subi.w	#CALC_SETUP_WORDS, d5
	bmi.s	rs_restore
	cmp.w	d5, d1
	bhi.s	rs_split_calc
	sub.w	d1, d5
	move.w	d1, d2
	move.w	10(a2), d1
	bsr	dma_word_ram
	bra.s	rs_next
rs_split:
	subi.w	#CALC_SETUP_WORDS, d5
	bmi.s	rs_restore
rs_split_calc:
	/* Transfer the whole patterns that fit and leave the rest of the
	   record, rewritten in place, for the next blank. */
	move.w	d5, d2
	andi.w	#0xFFF0, d2			/* prefix words, whole patterns */
	beq.s	rs_restore
	movem.l	d1/a0, -(sp)
	move.w	10(a2), d1			/* destination */
	bsr	dma_word_ram			/* a1 src, d1 dst, d2 words */
	movem.l	(sp)+, d1/a0
	sub.w	d2, d1
	ori.w	#0x8000, d1			/* mark: registers must be computed */
	move.w	d1, (a2)			/* remaining words */
	add.w	d2, 10(a2)
	add.w	d2, 10(a2)
	adda.w	d2, a1
	adda.w	d2, a1
	move.l	a1, 18(a2)
rs_restore:
	movea.l	a2, a0				/* resume this record next blank */
rs_save:
	move.l	a0, rec_ptr
	move.w	d6, rec_left
rs_ret:
	rts
rs_finished:
	move.l	a0, rec_ptr
	clr.w	rec_left
	move.l	rec_frame, rec_done
	clr.w	rec_go
	rts

/* DMA d2 words from Word RAM (Main view a1) to VRAM byte d1, then repair the
   destination's first word. trashes d0. */
dma_word_ram:
	move.l	a1, d0
	addq.l	#2, d0				/* Word-RAM DMA src+2 */
	bra.s	dma_common_src
/* DMA d2 words from Main RAM a1 to VRAM byte d1 (no repair). */
dma_main_ram:
	move.l	a1, d0
	bsr.s	dma_regs
	bra.s	dma_go
dma_common_src:
	bsr.s	dma_regs
	bsr.s	dma_go
	/* repair: the first word written by a Word-RAM DMA is stale */
	move.l	d1, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	move.w	(a1), (a5)
	rts

/* d0 = source byte address, d2 = words: write registers 93..97.
   trashes d0 only. */
dma_regs:
	move.l	d3, -(sp)
	lsr.l	#1, d0
	move.w	d2, d3
	andi.w	#0x00FF, d3
	ori.w	#0x9300, d3
	move.w	d3, (a6)
	move.w	d2, d3
	lsr.w	#8, d3
	ori.w	#0x9400, d3
	move.w	d3, (a6)
	move.w	d0, d3
	andi.w	#0x00FF, d3
	ori.w	#0x9500, d3
	move.w	d3, (a6)
	lsr.l	#8, d0
	move.w	d0, d3
	andi.w	#0x00FF, d3
	ori.w	#0x9600, d3
	move.w	d3, (a6)
	lsr.l	#8, d0
	move.w	d0, d3
	andi.w	#0x007F, d3
	ori.w	#0x9700, d3
	move.w	d3, (a6)
	move.l	(sp)+, d3
	rts

/* Start a VRAM DMA to byte d1 and wait for it. trashes d0. */
dma_go:
	move.l	d1, d0
	bsr.s	vram_write_cmd
	ori.w	#0x0080, d0			/* CD5: memory-to-VRAM DMA */
	move.l	d0, (a6)
1:
	move.w	(a6), d0
	btst	#1, d0
	bne.s	1b
	rts

/* d0.w = VRAM byte address -> d0.l = VRAM write command. */
vram_write_cmd:
	andi.l	#0x0000FFFF, d0
	lsl.l	#2, d0
	lsr.w	#2, d0
	swap	d0
	ori.l	#0x40000000, d0
	rts

/* Publish frame d6 (pub words at a4): final-only patterns, name table, CRAM. */
publish:
	lea	fin0, a3
	lea	shadow0, a2
	move.l	cram_ptr0, d5
	btst	#0, d6
	beq.s	1f
	lea	fin1, a3
	lea	shadow1, a2
	move.l	cram_ptr1, d5
1:
	move.w	0(a4), d4			/* final runs */
	beq.s	2f
	subq.w	#1, d4
1:
	move.w	(a3)+, d1
	move.w	(a3)+, d2
	movea.l	(a3)+, a1
	bsr	dma_main_ram
	dbra	d4, 1b
2:
	/* name table: the whole band in one DMA */
	movea.l	a2, a1
	move.w	p_nt, d1
	addi.w	#(PC_ROW0*64+PC_COL0)*2, d1
	move.w	#NT_BAND_WORDS, d2
	bsr	dma_main_ram
	tst.l	d5
	beq.s	1f
	movea.l	d5, a1
	move.l	a1, d0
	moveq	#64, d2
	bsr	dma_regs
	move.l	#0xC0000080, (a6)		/* CRAM 0, DMA */
2:
	move.w	(a6), d0
	btst	#1, d0
	bne.s	2b
1:
	clr.w	4(a4)
	move.l	d6, published
	/* cadence statistics */
	cmpi.l	#1, d6
	bhi.s	2f
	bne.s	3f
	move.w	vb_count, base_vb		/* frame 1 anchors the cadence */
	bra.s	3f
2:
	move.l	d6, d0
	subq.w	#1, d0
	mulu.w	#PC_VSYNC_N, d0
	add.w	base_vb, d0
	move.w	vb_count, d1
	sub.w	d0, d1				/* lateness */
	beq.s	3f
	addq.w	#1, late_frames
	cmp.w	max_late, d1
	bls.s	3f
	move.w	d1, max_late
3:
	rts

/* Frame -1: black CRAM, blank name table, zero scroll, movie registers. */
job_blank:
	move.w	p_reg0, d0
	btst	#1, p_flags+1
	bne.s	1f
	andi.w	#0xFFEF, d0			/* no horizontal interrupt */
1:
	move.w	d0, (a6)
	move.w	#0x8700, (a6)			/* backdrop: palette 0 colour 0 */
	move.l	#0xC0000000, (a6)
	moveq	#0, d0
	moveq	#32-1, d1
1:
	move.l	d0, (a5)
	dbra	d1, 1b
	move.l	#0x40000010, (a6)		/* VSRAM 0..1 */
	move.l	d0, (a5)
	move.w	p_hscroll, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	moveq	#0, d0
	move.l	d0, (a5)
	/* clear the 40x28 visible band of the movie name table */
	move.w	p_nt, d2
	moveq	#28-1, d3
2:
	move.w	d2, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	moveq	#0, d0
	moveq	#20-1, d1
1:
	move.l	d0, (a5)
	dbra	d1, 1b
	addi.w	#128, d2
	dbra	d3, 2b
	move.w	p_nt, d0
	lsr.w	#8, d0
	lsr.w	#2, d0				/* register 2: address >> 10 */
	ori.w	#0x8200, d0
	move.w	d0, (a6)
	move.w	p_nt, d0
	lsr.w	#8, d0
	lsr.w	#5, d0				/* register 4: address >> 13 */
	ori.w	#0x8400, d0
	move.w	d0, (a6)
	move.w	p_reg1, d0
	ori.w	#0x0070, d0			/* display, VInt and DMA enabled */
	move.w	d0, (a6)
	clr.w	vjob
	rts

/* Boot-stage sidecar: up to SIDECAR_PER_VBLANK records per blank. */
job_sidecar:
	move.w	#SIDECAR_PER_VBLANK-1, d5
	movea.l	sc_ptr, a0
	move.w	sc_left, d6
js_loop:
	tst.w	d6
	bne.s	js_record
	/* next region */
	move.w	sc_region, d0
	addq.w	#1, d0
	cmpi.w	#3, d0
	bhs.s	js_done
	move.w	d0, sc_region
	lea	sc_counts, a1
	add.w	d0, d0
	move.w	(a1,d0.w), d6
	lea	BOOT_STAGE+0x1000, a0
	cmpi.w	#2, d0
	beq.s	js_loop
	lea	BOOT_STAGE+0x5000, a0
	bra.s	js_loop
js_record:
	moveq	#0, d0
	move.w	(a0)+, d0			/* zero-based slot */
	cmpi.w	#PC_POOL, d0
	bhs.s	2f
	addq.w	#1, d0
	lsl.w	#5, d0
	bsr	vram_write_cmd
	move.l	d0, (a6)
	moveq	#8-1, d1
1:
	move.l	(a0)+, (a5)
	dbra	d1, 1b
	bra.s	3f
2:
	lea	32(a0), a0
3:
	subq.w	#1, d6
	dbra	d5, js_loop
	move.l	a0, sc_ptr
	move.w	d6, sc_left
	rts
js_done:
	clr.w	vjob
	rts

/* ------------------------------------------------------------------ */
	.align	2
paltab_image:
	.incbin	"paltab.bin"
palidx_image:
	.incbin	"palidx.bin"
	.align	2
image_end:

	.bss
	.align	2
bss_start:
p_nt:		.space 2
p_hscroll:	.space 2
p_reg0:		.space 2
p_reg1:		.space 2
p_reg2:		.space 2
p_reg4:		.space 2
p_reg7:		.space 2
p_vint_slot:	.space 4
p_flags:	.space 2
host_vint:	.space 4
host_sr:	.space 2
vjob:		.space 2
vb_count:	.space 2
vb_tick0:	.space 2
.ifdef IDLE_PROFILE
idle_active:	.space 2
idle_blank:	.space 2
idle_vb:	.space 2
hook_exit_v:	.space 2
sub_diag:	.space 8
idle_v:		.space 2
.endif
base_vb:	.space 2
published:	.space 4
late_frames:	.space 2
max_late:	.space 2
sub_slips:	.space 2
sub_desyncs:	.space 2
palidx_ptr:	.space 4
rec_frame:	.space 4
rec_done:	.space 4
rec_limit:	.space 4
rec_ptr:	.space 4
rec_left:	.space 2
rec_go:		.space 2
sc_ptr:		.space 4
sc_left:	.space 2
sc_region:	.space 2
sc_counts:	.space 6
cram_ptr0:	.space 4
cram_ptr1:	.space 4
pub0:		.space 6			/* final runs, cost, armed */
pub1:		.space 6
fin0:		.space FINAL_MAX_RUNS*8
fin1:		.space FINAL_MAX_RUNS*8
finbuf0:	.space FINAL_MAX_PATTERNS*32
finbuf1:	.space FINAL_MAX_PATTERNS*32
fade0:		.space 128
fade1:		.space 128
row_gap:	.space PC_BMBYTES*2
shadow0:	.space SHADOW_BYTES
shadow1:	.space SHADOW_BYTES
	.align	2
bss_end:
