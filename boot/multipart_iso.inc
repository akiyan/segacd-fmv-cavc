/* Bounded ISO9660 root reader shared by the two untimed loaders.
 * Persistent directory bounds live in the checked SP-GAP, not Word RAM:
 * the Word-RAM loader switches physical banks while keeping these bounds.
 * find_file: a0=exact ISO basename, returns d0=LBA, d1=sectors, d2=bytes.
 */
.equ ISO_DIRECTORY_BYTES, 0x00007F80
.equ ISO_VOLUME_SECTORS,  0x00007F84

init_iso9660:
	movem.l d0-d7/a0-a6, -(sp)
	moveq #16, d0
	moveq #1, d1
	lea ISO_BUF.l, a0
	bsr read_cd
	lea ISO_BUF.l, a1
	cmpi.l #0x01434430, (a1)
	bne loader_error
	cmpi.w #0x3031, 4(a1)
	bne loader_error
	cmpi.b #1, 6(a1)
	bne loader_error
	move.l 84(a1), d3
	cmpi.l #17, d3
	blo loader_error
	cmpi.l #360000, d3
	bhi loader_error
	move.l d3, (ISO_VOLUME_SECTORS).w
	lea 156(a1), a1
	cmpi.b #34, (a1)
	blo loader_error
	btst #1, 25(a1)
	beq loader_error
	move.l 14(a1), d2
	cmpi.l #34, d2
	blo loader_error
	cmpi.l #0x10000, d2
	bhi loader_error
	move.l d2, (ISO_DIRECTORY_BYTES).w
	move.l 6(a1), d0
	bsr iso_extent
	lea ISO_BUF.l, a0
	bsr read_cd
	movem.l (sp)+, d0-d7/a0-a6
	rts

/* Validate a nonempty extent before passing any count to a read loop. */
iso_extent:
	tst.l d2
	ble loader_error
	cmpi.l #360000*2048, d2
	bhi loader_error
	cmpi.l #17, d0
	blo loader_error
	move.l d2, d1
	addi.l #2047, d1
	moveq #11, d3
	lsr.l d3, d1
	move.l d0, d3
	add.l d1, d3
	bcs loader_error
	cmp.l (ISO_VOLUME_SECTORS).w, d3
	bhi loader_error
	rts

find_file:
	movem.l d3-d7/a1-a3/a6, -(sp)
	lea ISO_BUF.l, a1
	movea.l a1, a3
	adda.l (ISO_DIRECTORY_BYTES).w, a3
iso_record:
	cmpa.l a3, a1
	bhs loader_error
	moveq #0, d4
	move.b (a1), d4
	beq iso_padding
	cmpi.w #34, d4
	blo loader_error
	btst #0, d4
	bne loader_error
	movea.l a1, a2
	adda.w d4, a2
	cmpa.l a3, a2
	bhi loader_error
	move.l a1, d3
	andi.l #2047, d3
	add.w d4, d3
	cmpi.w #2048, d3
	bhi loader_error
	moveq #0, d5
	move.b 32(a1), d5
	move.w d5, d3
	addi.w #33, d3
	cmp.w d4, d3
	bhi loader_error
	btst #1, 25(a1)
	bne iso_next
	movea.l a0, a6
	lea 33(a1), a2
iso_name:
	move.b (a6)+, d3
	beq iso_name_end
	subq.w #1, d5
	bmi iso_next
	cmp.b (a2)+, d3
	bne iso_next
	bra.s iso_name
iso_name_end:
	cmpi.w #2, d5
	bne iso_next
	cmpi.b #59, (a2)+
	bne iso_next
	cmpi.b #49, (a2)
	bne iso_next
	move.l 6(a1), d0
	move.l 14(a1), d2
	bsr iso_extent
	movem.l (sp)+, d3-d7/a1-a3/a6
	rts
iso_next:
	adda.w d4, a1
	bra iso_record
iso_padding:
	move.l a1, d3
	andi.l #0xFFFFF800, d3
	addi.l #2048, d3
	movea.l d3, a1
	bra iso_record
