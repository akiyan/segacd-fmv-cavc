/*
 * In-game player test host, Sub CPU side.
 *
 * A stand-in for a game's own Sub program: a BIOS module at 0x6000 that
 * owns the drive and answers its Main program's commands. Command 1 plays
 * the movie: it loads MOVIES.BIN (the in-game Sub module) into PRG-RAM at
 * its link base and calls it with the ISO extents of HEADER.DAT and
 * BODY.DAT, exactly as a game would. See PLAYER.md (In-game player).
 *
 * Comm words: Main writes its command to 0xA12010; this program reports on
 * 0xA12020 (1 ready, 3 module running, 2 done), the module's status on
 * 0xA12022 and its slip count on 0xA12024. Command 3 starts the drive and
 * finds the files once Main has seen STAT_SUB_BOOTED; command 1 plays the
 * movie and command 2 acknowledges "done".
 */
	.include "sub_boot.inc"

.equ CDBIOS,         0x00005F22
.equ CDB_STAT,       0x00005E80
.equ BIOS_DRV_INIT,  0x0010
.equ BIOS_CDB_STAT,  0x0081
.equ BIOS_CDC_STOP,  0x0089
.equ BIOS_CDC_STAT,  0x008A
.equ BIOS_CDC_READ,  0x008B
.equ BIOS_CDC_TRN,   0x008C
.equ BIOS_CDC_ACK,   0x008D
.equ BIOS_ROM_READN, 0x0020

.equ SUB_GA_BASE, 0x00FF8000
.equ MEMMODE,     SUB_GA_BASE+0x0002
.equ COMCMD0,     SUB_GA_BASE+0x0010
.equ COMSTAT0,    SUB_GA_BASE+0x0020
.equ COMSTAT1,    SUB_GA_BASE+0x0022
.equ COMSTAT2,    SUB_GA_BASE+0x0024

.equ MODULE_BASE, 0x00040000		/* the in-game Sub module's link base */
.equ ISO_BUF,     0x00050000		/* boot-only directory scratch in the loan */
.equ MODULE_MAGIC, 0x43415653		/* "CAVS" */

.equ ST_READY,   1
.equ ST_DONE,    2
.equ ST_RUNNING, 3
.equ CMD_PLAY,   1
.equ CMD_ACK,    2
.equ CMD_INIT,   3

.macro BIOSCALL code
	move.w	#\code, d0
	jsr	CDBIOS
.endm

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
	.word	sp_idle-sp_jmptbl
	.word	sp_idle-sp_jmptbl
	.word	0

sp_init:
	move.w	#0, (COMSTAT0).l
	rts
sp_idle:
	rts

sp_main:
	move.w	#STAT_SUB_BOOTED, (COMSTAT0).l
	/* Hold the boot status until Main has seen it. */
1:
	cmpi.w	#CMD_INIT, (COMCMD0).l
	bne.s	1b
	ori.b	#0x04, (SUB_GA_BASE+0x37).l	/* CDD communication */
	ori.b	#0x3C, (SUB_GA_BASE+0x33).l	/* BIOS sector service interrupts */
	move.w	#0x2000, sr
	lea	track_list, a0
	BIOSCALL BIOS_DRV_INIT
1:
	BIOSCALL BIOS_CDB_STAT
	andi.b	#0xF0, (CDB_STAT).w
	bne	1b
	bsr	init_iso9660
	lea	file_header, a0
	bsr	find_file
	lea	extents, a1
	move.l	d0, (a1)+
	move.l	d1, (a1)+
	lea	file_body, a0
	bsr	find_file
	move.l	d0, (a1)+
	move.l	d1, (a1)+
	lea	file_module, a0
	bsr	find_file
	move.l	d0, module_lba
	move.l	d1, module_sectors
	/* 2M mode with Word RAM owned by Main, as the game keeps it. */
	move.b	#0x01, (MEMMODE+1).l
1:
	btst	#0, (MEMMODE+1).l
	beq.s	1b
ready:
	move.w	#ST_READY, (COMSTAT0).l
wait_cmd:
	cmpi.w	#CMD_PLAY, (COMCMD0).l
	bne.s	wait_cmd
	/* Load the module where it is linked to run, then hand over. */
	move.l	module_lba, d0
	move.l	module_sectors, d1
	lea	MODULE_BASE, a0
	bsr	read_cd
	lea	MODULE_BASE, a2
	moveq	#-1, d0
	cmpi.l	#MODULE_MAGIC, (a2)
	bne.s	1f
	cmpa.l	8(a2), a2
	bne.s	1f
	move.w	#ST_RUNNING, (COMSTAT0).l
	lea	extents, a0
	movea.l	16(a2), a2
	jsr	(a2)
1:
	move.w	d0, (COMSTAT1).l
	move.w	d1, (COMSTAT2).l
	move.w	#ST_DONE, (COMSTAT0).l
1:
	cmpi.w	#CMD_ACK, (COMCMD0).l
	bne.s	1b
	move.w	#ST_READY, (COMSTAT0).l
1:
	tst.w	(COMCMD0).l
	bne.s	1b
	bra	wait_cmd

/* Read d1 sectors from LBA d0 to a0 (finite, polled). The CDC can still
   hold sectors of an earlier read after STOP (the movie leaves BODY.DAT
   sectors behind), so every sector's header must carry the expected
   absolute frame (LBA + 150); others are discarded. */
read_cd:
	movem.l	d0-d7/a0-a6, -(sp)
	lea	bios_packet, a5
	move.l	d0, (a5)
	move.l	d1, 4(a5)
	move.l	a0, 8(a5)
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	movea.l	a5, a0
	BIOSCALL BIOS_ROM_READN
wait_stat:
	BIOSCALL BIOS_CDC_STAT
	bcs.s	wait_stat
wait_read:
	BIOSCALL BIOS_CDC_READ
	bcc.s	wait_read
wait_transfer:
	movea.l	8(a5), a0
	lea	12(a5), a1
	BIOSCALL BIOS_CDC_TRN
	bcc.s	wait_transfer
	BIOSCALL BIOS_CDC_ACK
	/* header M:S:F (BCD) -> absolute frame */
	lea	12(a5), a0
	move.b	(a0)+, d0
	bsr	bcd2bin
	move.w	d0, d2
	mulu	#60, d2
	move.b	(a0)+, d0
	bsr	bcd2bin
	add.w	d0, d2
	mulu	#75, d2
	move.b	(a0)+, d0
	bsr	bcd2bin
	add.l	d0, d2
	move.l	(a5), d3
	addi.l	#150, d3
	cmp.l	d3, d2
	bne.s	wait_stat			/* a stale sector: discard it */
	addq.l	#1, (a5)
	addi.l	#0x0800, 8(a5)
	subq.l	#1, 4(a5)
	bne.s	wait_stat
	movem.l	(sp)+, d0-d7/a0-a6
	rts

/* d0.b BCD -> d0.l binary. Trashes d1. */
bcd2bin:
	andi.l	#0xFF, d0
	move.w	d0, d1
	lsr.w	#4, d1
	mulu	#10, d1
	andi.w	#0x0F, d0
	add.w	d1, d0
	rts

init_iso9660:
	movem.l	d0-d7/a0-a6, -(sp)
	move.l	#0x10, d0
	move.l	#2, d1
	lea	ISO_BUF, a0
	bsr	read_cd
	lea	ISO_BUF, a0
	lea	156(a0), a1
	moveq	#0, d0
	move.b	6(a1), d0
	lsl.l	#8, d0
	move.b	7(a1), d0
	lsl.l	#8, d0
	move.b	8(a1), d0
	lsl.l	#8, d0
	move.b	9(a1), d0
	move.l	#0x20, d1
	lea	ISO_BUF, a0
	bsr	read_cd
	movem.l	(sp)+, d0-d7/a0-a6
	rts

/* a0 = file name -> d0 = LBA, d1 = sectors. */
find_file:
	movem.l	a1-a2/a6, -(sp)
	lea	ISO_BUF, a1
1:
	movea.l	a0, a6
	move.b	(a6)+, d0
2:
	movea.l	a1, a2
	cmp.b	(a1)+, d0
	bne.s	2b
3:
	move.b	(a6)+, d0
	beq.s	4f
	cmp.b	(a1)+, d0
	bne	1b
	bra.s	3b
4:
	sub.l	#33, a2
	moveq	#0, d0
	move.b	6(a2), d0
	lsl.l	#8, d0
	move.b	7(a2), d0
	lsl.l	#8, d0
	move.b	8(a2), d0
	lsl.l	#8, d0
	move.b	9(a2), d0
	moveq	#0, d1
	move.b	14(a2), d1
	lsl.l	#8, d1
	move.b	15(a2), d1
	lsl.l	#8, d1
	move.b	16(a2), d1
	lsl.l	#8, d1
	move.b	17(a2), d1
	add.l	#2047, d1
	moveq	#11, d2
	lsr.l	d2, d1
	movem.l	(sp)+, a1-a2/a6
	rts

track_list:
	.byte	1, 0xFF
file_header:
	.asciz	"HEADER.DAT"
file_body:
	.asciz	"BODY.DAT"
file_module:
	.asciz	"MOVIES.BIN"
	.align	2
bios_packet:
	.long	0, 0, 0, 0, 0
extents:
	.long	0, 0, 0, 0		/* HEADER LBA, sectors, BODY LBA, sectors */
module_lba:
	.long	0
module_sectors:
	.long	0
sp_end:
