/* Bootstrap Sub program for the separate multi-video menu build.
 *
 * The boot image only needs a small loader at the normal 0x6000 SP address.
 * It copies MENUSP.BIN into the same fixed Word-RAM slot in both physical
 * banks, then transfers control to the Word-RAM menu launcher. A selected
 * movie later replaces this bootstrap in the normal resident SP slot.
 */

.equ CDBIOS,        0x00005F22
.equ CDB_STAT,      0x00005E80
.equ BIOS_DRV_INIT, 0x0010
.equ BIOS_CDB_STAT, 0x0081
.equ BIOS_CDC_STOP, 0x0089
.equ BIOS_CDC_STAT, 0x008A
.equ BIOS_CDC_READ, 0x008B
.equ BIOS_CDC_TRN,  0x008C
.equ BIOS_CDC_ACK,  0x008D
.equ BIOS_ROM_READN,0x0020

.equ SUB_GA_BASE,   0x00FF8000
.equ MEMMODE,       SUB_GA_BASE+0x0002
.equ COMCMD1,       SUB_GA_BASE+0x0012
.equ COMSTAT0,      SUB_GA_BASE+0x0020
.equ SUB_BANK_1M,   0x000C0000
.equ ISO_BUF,       0x00067000
.equ SP_STACK,      0x0007FF00
.equ MENU_SP_WORD_OFF,   0x0001E000
.equ MENU_SP_WORD_ENTRY, 0x000DE000
.equ MULTI_WORD_SWAP_STUB, 0x00007F50
.equ MULTI_INT_STUB,     0x00007F64	/* after the 20-byte bank-switch stub */
.equ BIOS_USERCALL2_TGT, 0x00005F36
.equ BIOS_USERCALL3_TGT, 0x00005F3C
.equ MULTI_RETURN_ROUTINE, 0x0000D680	/* PRG-resident A-play menu return */
.equ MULTI_MENU_INFO,    0x00007F20
.equ MENU_IMAGE_OFF,     0x00000000
.equ MENU_IP_SECTORS,    10
.equ MENU_SP_SECTORS,    3
.equ STAT_MENU_IP_READY, 0x8006

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
	.word	sp_int2-sp_jmptbl
	.word	sp_user-sp_jmptbl
	.word	0

.global sp_init
sp_init:
	move.w	#0x2700, sr
	andi.w	#0xFFFA, (MEMMODE).l
	move.w	#0, (COMSTAT0).l
	rts

.global sp_main
sp_main:
	movea.l	#SP_STACK, sp
	ori.b	#0x04, (SUB_GA_BASE+0x37).l
	ori.b	#0x3C, (SUB_GA_BASE+0x33).l
	move.w	#0x2000, sr
	lea	drv_init_tracklist, a0
	BIOSCALL BIOS_DRV_INIT
1:
	BIOSCALL BIOS_CDB_STAT
	andi.b	#0xF0, (CDB_STAT).w
	bne.s	1b
	bsr	init_iso9660
	lea	file_menu_sp, a0
	bsr	find_file
	move.l	d0, menu_sp_lba
	move.l	d1, menu_sp_sectors

	/* The menu launcher executes from both banks, so keep a copy in each one. */
	bset	#2, (MEMMODE+1).l
	move.l	menu_sp_lba, d0
	move.l	menu_sp_sectors, d1
	lea	(SUB_BANK_1M+MENU_SP_WORD_OFF).l, a0
	bsr	read_cd
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.l	menu_sp_lba, d0
	move.l	menu_sp_sectors, d1
	lea	(SUB_BANK_1M+MENU_SP_WORD_OFF).l, a0
	bsr	read_cd
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	bsr	install_multi_word_swap_stub
	bsr	install_multi_return_routine
	/* The BIOS user vectors registered from this bootstrap image would point
	   into the resident SP slot after a selected player replaces it, so any
	   later INT2 (the Main BIOS VINT raises one on every VBlank while the
	   security license screen runs) would execute mid-player bytes as a
	   handler.  Re-point the INT2/user calls at a permanent rts in the
	   reserved PRG stub slot before any image swap can happen. */
	move.w	#0x4E75, (MULTI_INT_STUB).l
	move.l	#MULTI_INT_STUB, (BIOS_USERCALL2_TGT).l
	move.l	#MULTI_INT_STUB, (BIOS_USERCALL3_TGT).l
	jmp	(MENU_SP_WORD_ENTRY).l

/* Read d1 sectors from absolute LBA d0 to address a0. */
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
	addi.l	#2047, d1
	moveq	#11, d2
	lsr.l	d2, d1
	movem.l	(sp)+, a1-a2/a6
	rts

swap_settle:
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts

/* Install this tiny bank-switch routine in the fixed PRG-RAM gap.  The menu
   launcher runs from Word RAM, so its own code cannot safely toggle the bank
   that contains the currently executing copy. */
install_multi_word_swap_stub:
	lea	multi_word_swap_stub_image, a0
	movea.l	#MULTI_WORD_SWAP_STUB, a1
	moveq	#((multi_word_swap_stub_image_end-multi_word_swap_stub_image)/2)-1, d0
1:
	move.w	(a0)+, (a1)+
	dbra	d0, 1b
	rts

	.align	2
multi_word_swap_stub_image:
	bchg	#0, (MEMMODE+1).l
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts
multi_word_swap_stub_image_end:

/* Install the A-play menu-return routine in the unallocated RING-ALIGN gap.
   Every selected player jumps here at movie end, so it must survive both the
   bootstrap image (replaced by the selected SP) and Word RAM (replaced by
   WordBuf frames).  The image is position-independent: local branches only,
   locals addressed pc-relative, external references absolute. */
install_multi_return_routine:
	lea	multi_return_image, a0
	movea.l	#MULTI_RETURN_ROUTINE, a1
	move.w	#((multi_return_image_end-multi_return_image)/2)-1, d0
1:
	move.w	(a0)+, (a1)+
	dbra	d0, 1b
	rts

multi_return_image:
1:
	tst.w	(COMCMD1).l			/* Main requests the menu return */
	beq.s	1b
	move.l	(MULTI_MENU_INFO+8).w, d0	/* saved MENUIP extent */
	moveq	#MENU_IP_SECTORS, d1
	lea	(SUB_BANK_1M+MENU_IMAGE_OFF).l, a0
	bsr.w	mr_read_cd
	bchg	#0, (MEMMODE+1).l		/* menu image becomes Main-visible */
	bsr.w	mr_settle
	move.w	#STAT_MENU_IP_READY, (COMSTAT0).l
2:
	tst.w	(COMCMD1).l			/* Main drops the request when its
						   MENUIP copy is complete */
	bne.s	2b
	bchg	#0, (MEMMODE+1).l		/* Sub owns the bank again */
	bsr.w	mr_settle
	move.l	(MULTI_MENU_INFO).w, d0		/* saved MENUSP extent */
	moveq	#MENU_SP_SECTORS, d1
	lea	(SUB_BANK_1M+MENU_SP_WORD_OFF).l, a0
	bsr.w	mr_read_cd
	bchg	#0, (MEMMODE+1).l
	bsr.w	mr_settle
	bsr.w	mr_read_cd			/* same packet: second bank copy */
	jmp	(MENU_SP_WORD_ENTRY).l

mr_settle:
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts

mr_read_cd:
	movem.l	d0-d7/a0-a6, -(sp)
	lea	mr_packet(pc), a5
	move.l	d0, (a5)
	move.l	d1, 4(a5)
	move.l	a0, 8(a5)
	movea.l	a5, a0
	BIOSCALL BIOS_CDC_STOP
	BIOSCALL BIOS_ROM_READN
mr_stat:
	BIOSCALL BIOS_CDC_STAT
	bcs.s	mr_stat
mr_data:
	BIOSCALL BIOS_CDC_READ
	bcc.s	mr_data
mr_trn:
	movea.l	8(a5), a0
	lea	12(a5), a1
	BIOSCALL BIOS_CDC_TRN
	bcc.s	mr_trn
	BIOSCALL BIOS_CDC_ACK
	addq.l	#1, (a5)
	addi.l	#0x0800, 8(a5)
	subq.l	#1, 4(a5)
	bne.s	mr_stat
	movem.l	(sp)+, d0-d7/a0-a6
	rts
	.align	2
mr_packet:
	.long	0, 0, 0, 0, 0
multi_return_image_end:

	.align	2
drv_init_tracklist:
	.byte	1, 0xFF
file_menu_sp:
	.asciz	"MENUSP.BIN"

	.align	2
bios_packet:
	.long	0,0,0,0,0
menu_sp_lba:
	.long	0
menu_sp_sectors:
	.long	0

.global sp_int2
sp_int2:
	rts
.global sp_user
sp_user:
	rts

sp_end:
