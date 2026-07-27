/*
 * HEADER-preloaded Sub player extension.
 *
 * The packer stores these bytes in the unused padding after the 8,800-byte
 * ADPCM table. The resident base copies them from the five-sector HEADER stage
 * to the unused timed-ring tail. These entries run only during boot; frame-0
 * staging may overwrite their bytes after they return. a2 supplies the
 * profile-specific Word-RAM signed-delta destination.
 */

.equ MEMMODE,                 0x00FF8002
.equ ROUTING_TMP,             0x0007B000
.equ ADPCM_INDEX_TABLE,       0x0000C000
.equ ADPCM_OUTPUT_LUT,        0x0000CB20
.equ RING_BASE,               0x0000D000
.equ APPLY_BASE,              0x00077000
.equ ADPCM_INDEX_BYTES,       2848
.equ ADPCM_DELTA_BYTES,       5696
.equ ADPCM_OUTPUT_LUT_BYTES,  256
.equ ADPCM_DELTA_OFFSET,      ADPCM_INDEX_BYTES
.equ ADPCM_OUTPUT_LUT_OFFSET, ADPCM_INDEX_BYTES+ADPCM_DELTA_BYTES
.equ ADPCM_INDEX_LONGS,       ADPCM_INDEX_BYTES/4
.equ ADPCM_DELTA_LONGS,       ADPCM_DELTA_BYTES/4
.equ ADPCM_OUTPUT_LUT_LONGS,  ADPCM_OUTPUT_LUT_BYTES/4
.equ ADPCM_BANK_COPIES,       2
.equ ROUTING_CTRL_MASK,       0x0007
.equ ROUTING_TOTAL_SHIFT,     3
.equ ROUTING_MAX_ENTRY,       0x002D
.equ ROUTING_BANK_COPIES,     2

.text
.global adpcm_boot_copy
adpcm_boot_copy:
	/* Keep the on-disc 8,800-byte image unchanged. Copy only the runtime-hot
	   next-index and output tables into Sub-owned PRG-RAM. */
	lea	ROUTING_TMP, a0
	lea	ADPCM_INDEX_TABLE, a1
	move.w	#ADPCM_INDEX_LONGS-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b

	lea	ROUTING_TMP+ADPCM_OUTPUT_LUT_OFFSET, a0
	lea	ADPCM_OUTPUT_LUT, a1
	move.w	#ADPCM_OUTPUT_LUT_LONGS-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b

	/* The signed-delta table remains at its original offset in each physical
	   Word-RAM bank. The unused index/LUT holes stay reserved for an exact
	   player-only A/B with unchanged WordBuf capacities and stream bytes. */
	moveq	#ADPCM_BANK_COPIES-1, d1
2:
	lea	ROUTING_TMP+ADPCM_DELTA_OFFSET, a0
	movea.l	a2, a1
	move.w	#ADPCM_DELTA_LONGS-1, d0
1:
	move.l	(a0)+, (a1)+
	dbra	d0, 1b
	bchg	#0, (MEMMODE+1).l
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	dbra	d1, 2b
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
	bne.s	routing_invalid
	subq.w	#1, d7
1:
	moveq	#0, d0
	move.b	(a0)+, d0
	cmpi.b	#ROUTING_MAX_ENTRY, d0
	bhi.s	routing_invalid
	move.w	d0, d2
	andi.w	#ROUTING_CTRL_MASK, d0
	lsr.w	#ROUTING_TOTAL_SHIFT, d2
	cmp.w	d2, d0
	bhi.s	routing_invalid
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

	moveq	#0, d0
	rts

routing_invalid:
	moveq	#1, d0
	rts

	.align 4
adpcm_boot_copy_end:
