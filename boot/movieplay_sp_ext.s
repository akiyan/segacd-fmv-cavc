/*
 * HEADER-preloaded Sub player extension.
 *
 * The packer stores these bytes in the unused padding after the 8,800-byte
 * ADPCM table. The resident base copies them from the five-sector HEADER stage
 * to the unused timed-ring tail. This routine runs once; frame-0 staging may
 * overwrite its bytes after it returns. a2 supplies the profile-specific
 * Word-RAM signed-delta destination.
 */

.equ MEMMODE,                 0x00FF8002
.equ ROUTING_TMP,             0x0007B000
.equ ADPCM_INDEX_TABLE,       0x0000C000
.equ ADPCM_OUTPUT_LUT,        0x0000CB20
.equ ADPCM_INDEX_BYTES,       2848
.equ ADPCM_DELTA_BYTES,       5696
.equ ADPCM_OUTPUT_LUT_BYTES,  256
.equ ADPCM_DELTA_OFFSET,      ADPCM_INDEX_BYTES
.equ ADPCM_OUTPUT_LUT_OFFSET, ADPCM_INDEX_BYTES+ADPCM_DELTA_BYTES
.equ ADPCM_INDEX_LONGS,       ADPCM_INDEX_BYTES/4
.equ ADPCM_DELTA_LONGS,       ADPCM_DELTA_BYTES/4
.equ ADPCM_OUTPUT_LUT_LONGS,  ADPCM_OUTPUT_LUT_BYTES/4
.equ ADPCM_BANK_COPIES,       2

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

	.align 4
adpcm_boot_copy_end:
