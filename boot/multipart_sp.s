/*
 * Separate multi-video build - resident Sub launcher.
 *
 * This image owns only the boot/loader protocol.  It keeps PARTIP.BIN in both
 * physical 1M Word-RAM banks, loads one selected specialized IP into the
 * staging bank and one selected specialized SP into the resident SP slot, then
 * jumps to the selected player module. No video PrgBuf is reserved here.
 */

.equ CDBIOS,       0x00005F22
.equ CDB_STAT,     0x00005E80
.equ BIOS_DRV_INIT,0x0010
.equ BIOS_CDB_STAT,0x0081
.equ BIOS_CDC_STOP,0x0089
.equ BIOS_CDC_STAT,0x008A
.equ BIOS_CDC_READ,0x008B
.equ BIOS_CDC_TRN, 0x008C
.equ BIOS_CDC_ACK, 0x008D
.equ BIOS_ROM_READN,0x0020

.equ SUB_GA_BASE,  0x00FF8000
.equ MEMMODE,      SUB_GA_BASE+0x0002
.equ COMCMD0,      SUB_GA_BASE+0x0010
.equ COMCMD1,      SUB_GA_BASE+0x0012
.equ COMSTAT0,     SUB_GA_BASE+0x0020
.equ COMSTAT1,     SUB_GA_BASE+0x0022

.equ SUB_BANK_1M,  0x000C0000
.equ ISO_BUF,      0x00067000
.equ SP_STACK,     0x0007FF00

.include "multipart_sp.inc"

.include "multipart_cd_sector.inc"

.macro BIOSCALL code
	move.w	#\code, d0
	jsr	CDBIOS
.endm

.text

/* The loader launcher is linked into the upper end of the Sub-owned Word-RAM
   bank and runs there in 1M mode.  It must not clear the mode bit before its
   first instruction reaches the bank. */
.global loader_word_entry
loader_word_entry:
	move.w	#0x2700, sr
	move.w	#0, (COMSTAT0).l
	move.w	#0, (COMSTAT1).l
	bra.s	sp_main

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
	.word	sp_int2-sp_jmptbl
	.word	sp_user-sp_jmptbl
	.word	0

.global sp_init
sp_init:
	move.w	#0x2700, sr
	andi.w	#0xFFFA, (MEMMODE).l		/* 2M/clean mode for ISO directory */
	move.w	#0, (COMSTAT0).l
	move.w	#0, (COMSTAT1).l
	rts

.global sp_main
sp_main:
	movea.l	#SP_STACK, sp
	ori.b	#0x04, (SUB_GA_BASE+0x37).l	/* HOCK: enable CDD communication */
	ori.b	#0x3C, (SUB_GA_BASE+0x33).l	/* IEN: enable CDC/drive interrupts */
	move.w	#0x2000, sr
	lea	drv_init_tracklist, a0
	BIOSCALL BIOS_DRV_INIT
1:
	BIOSCALL BIOS_CDB_STAT
	andi.b	#0xF0, (CDB_STAT).w
	bne.s	1b
	bsr	init_iso9660
	lea	loader_sp_file, a0
	bsr	find_file
	move.l	d0, (MULTIPART_LOADER_INFO_ADDR).w
	lea	loader_ip_file, a0
	bsr	find_file
	/* These values survive the first Word-RAM bank switch. */
	move.l	d0, (MULTIPART_LOADER_RUNTIME_ADDR).l
	move.l	d1, (MULTIPART_LOADER_RUNTIME_ADDR+4).l
	move.l	d0, (MULTIPART_LOADER_INFO_ADDR+8).w
	cmp.l	#LOADER_IP_IMAGE_SECTORS, d1
	bne	loader_error

	/* Load the fixed-size loader image into both physical banks. */
	bset	#2, (MEMMODE+1).l
	move.l	(MULTIPART_LOADER_RUNTIME_ADDR).l, d0
	move.l	(MULTIPART_LOADER_RUNTIME_ADDR+4).l, d1
	lea	(SUB_BANK_1M+LOADER_IMAGE_OFF).l, a0
	bsr	read_cd
	jsr	(MULTIPART_WORD_SWAP_STUB).l
	move.l	(MULTIPART_LOADER_RUNTIME_ADDR).l, d0
	move.l	(MULTIPART_LOADER_RUNTIME_ADDR+4).l, d1
	lea	(SUB_BANK_1M+LOADER_IMAGE_OFF).l, a0
	bsr	read_cd

loader_ready:
	move.w	#STAT_LOADER_READY, (COMSTAT0).l

loader_command_loop:
	tst.w	(COMCMD0).l
	beq.s	loader_command_loop
	cmp.w	#CMD_LOADER_LOAD, (COMCMD0).l
	beq	load_selected
	/* Leave unrecognized commands visible until Main clears them. */
	move.w	(COMCMD0).l, (COMSTAT0).l
1:
	tst.w	(COMCMD0).l
	bne.s	1b
	bra	loader_ready

load_selected:
	move.w	(COMCMD1).l, d7
	move.w	d7, d6
	cmp.w	#LOADER_COUNT, d6
	bhs	loader_error
	/* Find and read the selected IP into the current Sub-owned 1M bank. */
	move.w	d6, d0
	lsl.w	#2, d0
	lea	loader_player_ip_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, selected_lba
	move.l	d1, selected_sectors
	tst.l d1
	beq loader_error
	cmpi.l #10, d1
	bhi loader_error
	bset	#2, (MEMMODE+1).l
	move.l	selected_lba, d0
	move.l	selected_sectors, d1
	lea	(SUB_BANK_1M+PLAYER_IP_STAGE_OFF).l, a0
	bsr	read_cd
	/* Make the staging bank visible to Main and wait for its copy ACK. */
	jsr	(MULTIPART_WORD_SWAP_STUB).l
	move.w	#STAT_LOADER_IP_READY, (COMSTAT0).l
3:
	tst.w	(COMCMD0).l
	bne.s	3b
	jsr	(MULTIPART_WORD_SWAP_STUB).l

	/* Save the selected stream extents in the marker-qualified low-PRG scratch.
	   The resident player can then start without another ISO directory scan. */
	move.w	d6, d0
	lsl.w	#2, d0
	lea	loader_player_header_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, (MULTIPART_LOADER_INFO_ADDR+16).w
	move.l	d1, (MULTIPART_LOADER_INFO_ADDR+20).w
	move.w	d6, d0
	lsl.w	#2, d0
	lea	loader_player_body_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, (MULTIPART_LOADER_INFO_ADDR+24).w
	move.l	d1, (MULTIPART_LOADER_INFO_ADDR+28).w

	/* The selected SP module is read to boot ISO scratch first.  ISO extents are
	   sector-rounded, while the resident SP slot is only 5 KiB; copying the
	   exact file length avoids spilling a third sector into ADP-IDX. */
	move.w	d6, d0
	lsl.w	#2, d0
	lea	loader_player_sp_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, (MULTIPART_SELECTED_SP_INFO_ADDR).l
	move.l	d1, (MULTIPART_SELECTED_SP_INFO_ADDR+4).l
	move.l	d2, (MULTIPART_SELECTED_SP_INFO_ADDR+8).l
	tst.l d2
	beq loader_error
	cmpi.l #5120, d2
	bhi loader_error
	btst #0, d2
	bne loader_error
	move.l	(MULTIPART_SELECTED_SP_INFO_ADDR).l, d0
	move.l	(MULTIPART_SELECTED_SP_INFO_ADDR+4).l, d1
	lea	ISO_BUF.l, a0
	bsr	read_cd
	lea	ISO_BUF.l, a0
	lea	PLAYER_SP_BASE.l, a1
	move.l	(MULTIPART_SELECTED_SP_INFO_ADDR+8).l, d0
	lsr.w	#1, d0
	beq.s	selected_sp_ready
	subq.w	#1, d0
1:
	move.w	(a0)+, (a1)+
	dbra	d0, 1b
selected_sp_ready:
	clr.w	(COMCMD1).l
	move.w	#STAT_PLAYER_READY, (COMSTAT0).l
	move.w d6, d0
	lsl.w #2, d0
	lea multipart_sp_entries, a0
	movea.l (a0,d0.w), a0
	jmp (a0)

swap_settle:
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts

loader_error:
	move.w	#0xDEAD, (COMSTAT0).l
1:
	bra.s	1b

/* Read d1 sectors from absolute LBA d0 to address a0.  The loader is stopped
   between files, so the BIOS synchronous transfer helper is sufficient here. */
read_cd:
	tst.l d1
	ble loader_error
	movem.l	d0-d7/a0-a6, -(sp)
	lea	bios_packet, a5
	move.l	d0, (a5)
	move.l	d1, 4(a5)
	move.l	a0, 8(a5)
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	/* Movie selection has no running PCM or timed BODY read. Give a
	 * physical drive 100 ms after STOP before requesting another extent. */
	move.w	(0xFFFF800C).w, d2
1:
	move.w	(0xFFFF800C).w, d3
	sub.w	d2, d3
	andi.w	#0x0FFF, d3
	cmpi.w	#3256, d3
	blo.s	1b
	movea.l	a5, a0
	BIOSCALL BIOS_ROM_READN
	move.w	#75, 16(a5)
read_stat:
	BIOSCALL BIOS_CDC_STAT
	bcs.s	read_stat
read_data:
	BIOSCALL BIOS_CDC_READ
	bcc.s	read_data
read_transfer:
	movea.l	8(a5), a0
	lea	12(a5), a1
	BIOSCALL BIOS_CDC_TRN
	bcc.s	read_transfer
	BIOSCALL BIOS_CDC_ACK
	MULTIPART_CHECK_SECTOR read_stat
	addq.l	#1, (a5)
	addi.l	#0x0800, 8(a5)
	subq.l	#1, 4(a5)
	bne.w	read_stat
	movem.l	(sp)+, d0-d7/a0-a6
	rts

	.include "multipart_iso.inc"

	.align	2
drv_init_tracklist:
	.byte	1, 0xFF

	bios_packet:
	.long	0,0,0,0,0
selected_lba:
	.long	0
selected_sectors:
	.long	0
.global sp_int2
sp_int2:
	rts
.global sp_user
sp_user:
	rts

sp_end:
