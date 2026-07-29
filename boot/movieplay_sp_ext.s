/*
 * HEADER-preloaded Sub player extension.
 *
 * The packer stores these bytes in the unused padding after the 8,800-byte
 * ADPCM table. The resident base copies them from the five-sector HEADER stage
 * to the unused timed-ring tail. These entries run only during boot; frame-0
 * staging may overwrite their bytes after they return.
 */

.equ MEMMODE,                 0x00FF8002
.equ ROUTING_TMP,             0x0007B000
.ifndef ISO_VERIFY_SP_TAIL
.equ ADPCM_INDEX_TABLE,       0x00007400
.else
.equ ADPCM_INDEX_TABLE,       0x00008600
.endif
.equ ADPCM_OUTPUT_LUT,        0x00009600
.equ ADPCM_DELTA_TABLE,       0x0000C000
.equ RING_BASE,               0x0000D800
.ifndef ISO_VERIFY_SP_TAIL
.equ APPLY_BASE,              0x00077000
.else
.equ APPLY_BASE,              0x00077800
.endif
.equ ADPCM_INDEX_BYTES,       2848
.equ ADPCM_DELTA_BYTES,       5696
.equ ADPCM_OUTPUT_LUT_BYTES,  256
.equ ADPCM_DELTA_OFFSET,      ADPCM_INDEX_BYTES
.equ ADPCM_OUTPUT_LUT_OFFSET, ADPCM_INDEX_BYTES+ADPCM_DELTA_BYTES
.equ ADPCM_INDEX_LONGS,       ADPCM_INDEX_BYTES/4
.equ ADPCM_DELTA_LONGS,       ADPCM_DELTA_BYTES/4
.equ ADPCM_OUTPUT_LUT_LONGS,  ADPCM_OUTPUT_LUT_BYTES/4
.equ PCM_ENV,                 0x00FF0001
.equ PCM_PAN,                 0x00FF0003
.equ PCM_FDL,                 0x00FF0005
.equ PCM_FDH,                 0x00FF0007
.equ PCM_LSL,                 0x00FF0009
.equ PCM_LSH,                 0x00FF000B
.equ PCM_ST,                  0x00FF000D
.equ PCM_CTRL,                0x00FF000F
.equ PCM_ONOFF,               0x00FF0011
.equ PCM_WAVE,                0x00FF2001
.equ WAVE_RING_END,           0x8000
.equ PCM_BOOT_INIT_OFF,       0x0300
.equ SP_TAIL_MARKER_BASE,      0x00007400
.equ SP_TAIL_MARKER_END,       0x00008000
.equ SP_TAIL_MARKER_XOR,       0xA55A
.equ SP_TAIL_CHECK_BASE,       0x00009700
.equ SP_TAIL_CHECK_STATE,      0x000097FC
.equ ROUTING_CTRL_MASK,       0x0007
.equ ROUTING_CTRL_COUNT_MASK, 0x0003
.equ ROUTING_WORD4_FLAG,      0x0004
.equ ROUTING_TOTAL_SHIFT,     3
.equ ROUTING_TOTAL_MASK,      0x0038
.equ ROUTING_WORD_SHIFT,      6
.equ ROUTING_WORD_MASK,       0x00C0
.equ ROUTING_MAX_ENTRY,       0x00ED
.equ ROUTING_BANK_COPIES,     2

.text
.global adpcm_boot_copy
adpcm_boot_copy:
	/* Keep the on-disc 8,800-byte image unchanged. Copy all three runtime-hot
	   decode tables once into Sub-owned PRG-RAM. */
	lea	ROUTING_TMP, a0
	lea	ADPCM_INDEX_TABLE, a1
	move.w	#ADPCM_INDEX_LONGS-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b

	lea	ROUTING_TMP+ADPCM_DELTA_OFFSET, a0
	lea	ADPCM_DELTA_TABLE, a1
	move.w	#ADPCM_DELTA_LONGS-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b

	lea	ROUTING_TMP+ADPCM_OUTPUT_LUT_OFFSET, a0
	lea	ADPCM_OUTPUT_LUT, a1
	move.w	#ADPCM_OUTPUT_LUT_LONGS-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b

	rts

/* Fixed second entry at extension base + 0x58.  For routes up to 8 KiB it
   executes in place after prebuffer; longer-route builds copy the complete
   extension to its ring-tail execution address before routing is staged.

   Validate ROUTING_TMP's d7-entry packed route, then copy d5 longs to a1 in
   both physical Word-RAM banks. On success, d6 supplies the exact prebuffer
   pattern count, a4 points at the contiguous ring/apply/frame state, and a5
   points at drain_k/write_ptr/f0_expand. Initialize that boot-only state here
   so the fixed-cadence resident image keeps its complete DEBUG path inside
   4 KiB. Return d0=0 on success or d0=1 on invalid input. The two bank toggles
   restore the caller's original bank phase. */
.org 0x0058
.global routing_prepare
routing_prepare:
	lea	ROUTING_TMP, a0
	movea.l	a0, a2
	movea.l	a1, a3
	tst.b	(a0)
	bne	routing_invalid
	subq.w	#1, d7
1:
	moveq	#0, d0
	move.b	(a0)+, d0
	cmpi.b	#ROUTING_MAX_ENTRY, d0
	bhi	routing_invalid
	move.w	d0, d2
	move.w	d0, d3
	andi.w	#ROUTING_CTRL_MASK, d0
	andi.w	#ROUTING_TOTAL_MASK, d2
	lsr.w	#ROUTING_TOTAL_SHIFT, d2
	cmpi.w	#5, d2
	bhi	routing_invalid
	cmp.w	d2, d0
	bhi	routing_invalid
	andi.w	#ROUTING_WORD_MASK, d3
	lsr.w	#ROUTING_WORD_SHIFT, d3
	btst	#2, d0
	beq.s	2f
	cmpi.w	#3, d3
	bne	routing_invalid
	andi.w	#ROUTING_CTRL_COUNT_MASK, d0
	addq.w	#1, d3
2:
	sub.w	d0, d2
	cmp.w	d2, d3
	bhi	routing_invalid
	dbra	d7, 1b

	moveq	#ROUTING_BANK_COPIES-1, d1
2:
	movea.l	a2, a0
	movea.l	a3, a1
	move.w	d5, d0
	subq.w	#1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b
	bchg	#0, (MEMMODE+1).l
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	dbra	d1, 2b

	/* ring_head, ring_tail, apply_tail, apply_cur and frame_idx are contiguous
	   in the resident image. drain_k, write_ptr and f0_expand form the second
	   checked group. These values are needed only once before frame 0 expands. */
	move.l	#RING_BASE, (a4)+
	lsl.l	#5, d6
	add.l	#RING_BASE, d6
	move.l	d6, (a4)+
	move.l	#APPLY_BASE, (a4)+
	move.l	#APPLY_BASE, (a4)+
	move.w	#1, (a4)
	clr.w	(a5)
	move.w	#1, 4(a5)

.ifdef ISO_VERIFY_SP_TAIL
	/* Diagnostic build only: install a tiny read-only checker in the already
	   qualified 0x9700 scratch page, then fill the complete reclaimed SP tail
	   with address-derived words. The resident timed image calls the checker
	   once per frame; 32 words per call cover all 3 KiB every 48 frames. */
	lea	sp_tail_check_image, a0
	lea	SP_TAIL_CHECK_BASE, a1
	move.w	#(sp_tail_check_end-sp_tail_check_image)/4-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b
	move.l	#SP_TAIL_MARKER_BASE, (SP_TAIL_CHECK_STATE).l
	lea	SP_TAIL_MARKER_BASE, a0
	move.w	#(SP_TAIL_MARKER_END-SP_TAIL_MARKER_BASE)/2-1, d0
1:
	move.l	a0, d1
	eori.w	#SP_TAIL_MARKER_XOR, d1
	move.w	d1, (a0)+
	dbra	d0, 1b
.endif
	moveq	#0, d0
	rts

routing_invalid:
	moveq	#1, d0
	rts

.ifdef ISO_VERIFY_SP_TAIL
	/* Copied to SP_TAIL_CHECK_BASE by adpcm_boot_copy. It returns d0=0 for a
	   clean 64-byte slice and d0=1 on the first changed word. Internal branches
	   remain valid after relocation because the complete image moves together. */
	.align 4
sp_tail_check_image:
	movem.l	d1/a0, -(sp)
	movea.l	(SP_TAIL_CHECK_STATE).l, a0
	moveq	#31, d0
1:
	move.l	a0, d1
	eori.w	#SP_TAIL_MARKER_XOR, d1
	cmp.w	(a0)+, d1
	bne.s	3f
	dbra	d0, 1b
	cmpa.l	#SP_TAIL_MARKER_END, a0
	blo.s	2f
	lea	SP_TAIL_MARKER_BASE, a0
2:
	move.l	a0, (SP_TAIL_CHECK_STATE).l
	moveq	#0, d0
	movem.l	(sp)+, d1/a0
	rts
3:
	moveq	#1, d0
	movem.l	(sp)+, d1/a0
	rts
	.align 4
sp_tail_check_end:
.endif

/* Boot-only wave-RAM clear and channel setup. d0 supplies the RF5C164
   frequency delta from the authenticated profile header. Keeping this large
   one-shot loop out of the resident image makes 0x7400 the hard SP boundary. */
.org PCM_BOOT_INIT_OFF
.global pcm_boot_init
pcm_boot_init:
	movem.l	d1-d3/a0, -(sp)
	move.w	d0, d3
	move.b	#0xFF, (PCM_ONOFF).l
	moveq	#0, d2
1:
	move.w	d2, d1
	andi.w	#0x0FFF, d1
	bne.s	2f
	move.w	d2, d0
	lsr.w	#8, d0
	lsr.w	#4, d0
	ori.b	#0x80, d0
	move.b	d0, (PCM_CTRL).l
2:
	lea	(PCM_WAVE).l, a0
	add.w	d1, d1
	adda.w	d1, a0
	move.b	#0x00, (a0)
	addq.w	#1, d2
	cmp.w	#WAVE_RING_END, d2
	blo.s	1b
	move.b	#0x88, (PCM_CTRL).l
	move.b	#0xFF, (PCM_WAVE).l
	move.b	#0xC0, (PCM_CTRL).l
	move.b	#0xFF, (PCM_ENV).l
	nop
	nop
	move.b	#0xFF, (PCM_PAN).l
	nop
	nop
	move.b	d3, (PCM_FDL).l
	nop
	nop
	lsr.w	#8, d3
	move.b	d3, (PCM_FDH).l
	nop
	nop
	move.b	#0x00, (PCM_LSL).l
	nop
	nop
	move.b	#0x00, (PCM_LSH).l
	nop
	nop
	move.b	#0x30, (PCM_ST).l
	movem.l	(sp)+, d1-d3/a0
	rts

	.align 4
adpcm_boot_copy_end:
