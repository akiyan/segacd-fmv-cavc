/* Finite loader reads can receive a buffered sector from the preceding read.
 * CDC_TRN writes its BCD MSF header at packet+12. ACK every sector, but advance
 * the destination only when its absolute LBA matches packet+0. A bounded
 * mismatch budget keeps corrupt headers from creating an unbounded scan.
 * Caller: a5=20-byte BIOS packet; d2-d4 scratch; retry=CDC_STAT loop.
 */
.macro MULTI_CHECK_SECTOR retry
	moveq	#0, d2
	move.b	12(a5), d2
	move.w	d2, d3
	andi.w	#15, d2
	lsr.w	#4, d3
	mulu.w	#10, d3
	add.w	d3, d2
	mulu.w	#60, d2
	moveq	#0, d3
	move.b	13(a5), d3
	move.w	d3, d4
	andi.w	#15, d3
	lsr.w	#4, d4
	mulu.w	#10, d4
	add.w	d4, d3
	add.w	d3, d2
	mulu.w	#75, d2
	moveq	#0, d3
	move.b	14(a5), d3
	move.w	d3, d4
	andi.w	#15, d3
	lsr.w	#4, d4
	mulu.w	#10, d4
	add.w	d4, d3
	add.l	d3, d2
	subi.l	#150, d2
	cmp.l	(a5), d2
	beq.s	.Lsector_ok\@
	/* A past sector can be discarded, but a future sector proves the
	 * required one was missed. Re-read the remaining extent at its exact
	 * destination instead of waiting for a sector the drive has passed. */
	blo.s	.Lsector_retry\@
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	movea.l	a5, a0
	BIOSCALL BIOS_ROM_READN
.Lsector_retry\@:
	subq.w	#1, 16(a5)
	bne.w	\retry
	move.w	#0xDEAD, (COMSTAT0).l
.Lsector_error\@:
	bra.s	.Lsector_error\@
.Lsector_ok\@:
.endm
