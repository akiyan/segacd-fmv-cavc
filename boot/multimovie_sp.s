/*
 * Separate multi-video build - resident Sub launcher.
 *
 * This image owns only the boot/menu protocol.  It keeps MENUIP.BIN in both
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

.include "multimovie_sp.inc"

.macro BIOSCALL code
	move.w	#\code, d0
	jsr	CDBIOS
.endm

.text

.ifdef MULTI_MENU_WORD
/* The menu launcher is linked into the upper end of the Sub-owned Word-RAM
   bank and runs there in 1M mode.  It must not clear the mode bit before its
   first instruction reaches the bank. */
.global menu_word_entry
menu_word_entry:
	move.w	#0x2700, sr
	move.w	#0, (COMSTAT0).l
	move.w	#0, (COMSTAT1).l
	bra.s	sp_main
.endif

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
	.ifndef MULTI_MENU_WORD
	andi.b	#0xFA, (MEMMODE+1).l
	.endif
	lea	drv_init_tracklist, a0
	BIOSCALL BIOS_DRV_INIT
1:
	BIOSCALL BIOS_CDB_STAT
	andi.b	#0xF0, (CDB_STAT).w
	bne.s	1b
	bsr	init_iso9660
	lea	menu_sp_file, a0
	bsr	find_file
	move.l	d0, (MULTI_MENU_INFO_ADDR).w
	lea	menu_ip_file, a0
	bsr	find_file
	move.l	d0, menu_ip_lba
	move.l	d1, menu_ip_sectors
	move.l	d0, (MULTI_MENU_INFO_ADDR+8).w
	cmp.l	#MENU_IP_IMAGE_SECTORS, d1
	bne	menu_error

	/* Load the fixed-size menu image into both physical banks. */
	bset	#2, (MEMMODE+1).l
	move.l	menu_ip_lba, d0
	move.l	menu_ip_sectors, d1
	lea	(SUB_BANK_1M+MENU_IMAGE_OFF).l, a0
	bsr	read_cd
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.l	menu_ip_lba, d0
	move.l	menu_ip_sectors, d1
	lea	(SUB_BANK_1M+MENU_IMAGE_OFF).l, a0
	bsr	read_cd
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle

menu_ready:
	move.w	#STAT_MENU_READY, (COMSTAT0).l

menu_command_loop:
	tst.w	(COMCMD0).l
	beq.s	menu_command_loop
	cmp.w	#CMD_MENU_LOAD, (COMCMD0).l
	beq	load_selected
	/* Leave unrecognized commands visible until Main clears them. */
	move.w	(COMCMD0).l, (COMSTAT0).l
1:
	tst.w	(COMCMD0).l
	bne.s	1b
	bra	menu_ready

load_selected:
	move.w	(COMCMD1).l, d7
	move.w	d7, d6
	andi.w	#0x7FFF, d6
	cmp.w	#MENU_COUNT, d6
	bhs	menu_error
	btst	#15, d7
	beq.s	1f
	move.w	#1, (MULTI_LOOP_FLAG_ADDR).w
	bra.s	2f
1:
	clr.w	(MULTI_LOOP_FLAG_ADDR).w
2:
	/* Find and read the selected IP into the current Sub-owned 1M bank. */
	move.w	d6, d0
	lsl.w	#2, d0
	lea	menu_player_ip_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, selected_lba
	move.l	d1, selected_sectors
	bset	#2, (MEMMODE+1).l
	move.l	selected_lba, d0
	move.l	selected_sectors, d1
	lea	(SUB_BANK_1M+PLAYER_IP_STAGE_OFF).l, a0
	bsr	read_cd
	/* Make the staging bank visible to Main and wait for its copy ACK. */
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.w	#STAT_MENU_IP_READY, (COMSTAT0).l
3:
	tst.w	(COMCMD0).l
	bne.s	3b
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle

	/* Save the selected stream extents in the marker-qualified low-PRG scratch.
	   The resident player can then start without another ISO directory scan. */
	move.w	d6, d0
	lsl.w	#2, d0
	lea	menu_player_header_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, (MULTI_MENU_INFO_ADDR+16).w
	move.l	d1, (MULTI_MENU_INFO_ADDR+20).w
	move.w	d6, d0
	lsl.w	#2, d0
	lea	menu_player_body_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, (MULTI_MENU_INFO_ADDR+24).w
	move.l	d1, (MULTI_MENU_INFO_ADDR+28).w

	/* The selected SP module is read to boot ISO scratch first.  ISO extents are
	   sector-rounded, while the resident SP slot is only 5 KiB; copying the
	   exact file length avoids spilling a third sector into ADP-IDX. */
	move.w	d6, d0
	lsl.w	#2, d0
	lea	menu_player_sp_names, a0
	movea.l	(a0,d0.w), a0
	bsr	find_file
	move.l	d0, selected_sp_lba
	move.l	d1, selected_sp_sectors
	move.l	d2, selected_sp_bytes
	move.l	selected_sp_lba, d0
	move.l	selected_sp_sectors, d1
	lea	ISO_BUF.l, a0
	bsr	read_cd
	lea	ISO_BUF.l, a0
	lea	PLAYER_SP_BASE.l, a1
	move.w	selected_sp_bytes, d0
	lsr.w	#1, d0
	beq.s	selected_sp_ready
	subq.w	#1, d0
1:
	move.w	(a0)+, (a1)+
	dbra	d0, 1b
selected_sp_ready:
	clr.w	(COMCMD1).l
	move.w	#STAT_PLAYER_READY, (COMSTAT0).l
	jmp	(PLAYER_SP_BASE).l

menu_error:
	move.w	#0xDEAD, (COMSTAT0).l
1:
	bra.s	1b

/* Read d1 sectors from absolute LBA d0 to address a0.  The menu is stopped
   between files, so the BIOS synchronous transfer helper is sufficient here. */
read_cd:
	movem.l	d0-d7/a0-a6, -(sp)
	lea	bios_packet, a5
	move.l	d0, (a5)
	move.l	d1, 4(a5)
	move.l	a0, 8(a5)
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	BIOSCALL BIOS_ROM_READN
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
	addq.l	#1, (a5)
	addi.l	#0x0800, 8(a5)
	subq.l	#1, 4(a5)
	bne.s	read_stat
	movem.l	(sp)+, d0-d7/a0-a6
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

/* Match the ISO9660 directory record format used by the normal player.
   Return d0=LBA, d1=sector-rounded length, d2=exact byte length. */
find_file:
	movem.l	a1-a2/a6, -(sp)
	lea	ISO_BUF, a1
find_filename_start:
	movea.l	a0, a6
	move.b	(a6)+, d0
find_first_char:
	movea.l	a1, a2
	cmp.b	(a1)+, d0
	bne.s	find_first_char
check_filename_chars:
	move.b	(a6)+, d0
	beq.s	find_file_info
	cmp.b	(a1)+, d0
	bne.s	find_filename_start
	bra.s	check_filename_chars
find_file_info:
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
	move.l	d1, d2			/* exact big-endian file length */
	add.l	#2047, d1
	moveq	#11, d3
	lsr.l	d3, d1
	movem.l	(sp)+, a1-a2/a6
	rts

swap_settle:
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts

	.align	2
drv_init_tracklist:
	.byte	1, 0xFF

	bios_packet:
	.long	0,0,0,0,0
menu_ip_lba:
	.long	0
menu_ip_sectors:
	.long	0
selected_lba:
	.long	0
selected_sectors:
	.long	0
selected_sp_lba:
	.long	0
selected_sp_sectors:
	.long	0
selected_sp_bytes:
	.long	0

.global sp_int2
sp_int2:
	rts
.global sp_user
sp_user:
	rts

sp_end:
