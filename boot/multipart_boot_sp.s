/* Bootstrap Sub program for the separate multi-video loader build.
 *
 * The boot image only needs a small loader at the normal 0x6000 SP address.
 * It copies PARTSP.BIN into the same fixed Word-RAM slot in both physical
 * banks, then transfers control to the Word-RAM loader launcher. A selected
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
.equ LOADER_SP_WORD_OFF,   0x0001E000
.equ LOADER_SP_WORD_ENTRY, 0x000DE000
.equ MULTIPART_WORD_SWAP_STUB, 0x00007F50
.equ MULTIPART_INT_STUB,     0x00007F64	/* after the 20-byte bank-switch stub */
.equ BIOS_USERCALL2_TGT, 0x00005F36
.equ BIOS_USERCALL3_TGT, 0x00005F3C
.equ MULTIPART_RETURN_ROUTINE, 0x0000D680	/* PRG-resident multipart return */
.equ MULTIPART_LOADER_INFO,    0x00007F20
.equ LOADER_IMAGE_OFF,     0x00000000
.equ LOADER_IP_SECTORS,    10
.equ LOADER_SP_SECTORS,    4
.equ STAT_LOADER_IP_READY, 0x8006

.include "multipart_cd_sector.inc"

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
	lea	file_loader_sp, a0
	bsr	find_file
	cmpi.l #LOADER_SP_SECTORS, d1
	bne loader_error
	move.l	d0, loader_sp_lba
	move.l	d1, loader_sp_sectors

	/* The loader launcher executes from both banks, so keep a copy in each one. */
	bset	#2, (MEMMODE+1).l
	move.l	loader_sp_lba, d0
	move.l	loader_sp_sectors, d1
	lea	(SUB_BANK_1M+LOADER_SP_WORD_OFF).l, a0
	bsr	read_cd
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	move.l	loader_sp_lba, d0
	move.l	loader_sp_sectors, d1
	lea	(SUB_BANK_1M+LOADER_SP_WORD_OFF).l, a0
	bsr	read_cd
	bchg	#0, (MEMMODE+1).l
	bsr	swap_settle
	bsr	install_multipart_word_swap_stub
	bsr	install_multipart_return_routine
	/* The BIOS user vectors registered from this bootstrap image would point
	   into the resident SP slot after a selected player replaces it, so any
	   later INT2 (the Main BIOS VINT raises one on every VBlank while the
	   security license screen runs) would execute mid-player bytes as a
	   handler.  Re-point the INT2/user calls at a permanent rts in the
	   reserved PRG stub slot before any image swap can happen. */
	move.w	#0x4E75, (MULTIPART_INT_STUB).l
	move.l	#MULTIPART_INT_STUB, (BIOS_USERCALL2_TGT).l
	move.l	#MULTIPART_INT_STUB, (BIOS_USERCALL3_TGT).l
	jmp	(LOADER_SP_WORD_ENTRY).l

/* Read d1 sectors from absolute LBA d0 to address a0. */
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

swap_settle:
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts

/* Install this tiny bank-switch routine in the fixed PRG-RAM gap.  The loader
   launcher runs from Word RAM, so its own code cannot safely toggle the bank
   that contains the currently executing copy. */
install_multipart_word_swap_stub:
	lea	multipart_word_swap_stub_image, a0
	movea.l	#MULTIPART_WORD_SWAP_STUB, a1
	moveq	#((multipart_word_swap_stub_image_end-multipart_word_swap_stub_image)/2)-1, d0
1:
	move.w	(a0)+, (a1)+
	dbra	d0, 1b
	rts

	.align	2
multipart_word_swap_stub_image:
	bchg	#0, (MEMMODE+1).l
1:
	btst	#1, (MEMMODE+1).l
	bne.s	1b
	rts
multipart_word_swap_stub_image_end:

/* Install the multipart return routine in the reserved RING-ALIGN overlay.
   Every selected player jumps here at movie end, so it must survive both the
   bootstrap image (replaced by the selected SP) and Word RAM (replaced by
   WordBuf frames).  The image is position-independent: local branches only,
   locals addressed pc-relative, external references absolute. */
install_multipart_return_routine:
	lea	multipart_return_image, a0
	movea.l	#MULTIPART_RETURN_ROUTINE, a1
	move.w	#((multipart_return_image_end-multipart_return_image)/2)-1, d0
1:
	move.w	(a0)+, (a1)+
	dbra	d0, 1b
	rts

multipart_return_image:
1:
	tst.w	(COMCMD1).l			/* Main requests the loader return */
	beq.s	1b
	move.l	(MULTIPART_LOADER_INFO+8).w, d0	/* saved LOADERIP extent */
	moveq	#LOADER_IP_SECTORS, d1
	lea	(SUB_BANK_1M+LOADER_IMAGE_OFF).l, a0
	bsr.w	mr_read_cd
	bchg	#0, (MEMMODE+1).l		/* loader image becomes Main-visible */
	bsr.w	mr_settle
	move.w	#STAT_LOADER_IP_READY, (COMSTAT0).l
2:
	tst.w	(COMCMD1).l			/* Main drops the request when its
						   LOADERIP copy is complete */
	bne.s	2b
	bchg	#0, (MEMMODE+1).l		/* Sub owns the bank again */
	bsr.w	mr_settle
	move.l	(MULTIPART_LOADER_INFO).w, d0		/* saved LOADERSP extent */
	moveq	#LOADER_SP_SECTORS, d1
	lea	(SUB_BANK_1M+LOADER_SP_WORD_OFF).l, a0
	bsr.w	mr_read_cd
	bchg	#0, (MEMMODE+1).l
	bsr.w	mr_settle
	bsr.w	mr_read_cd			/* same packet: second bank copy */
	jmp	(LOADER_SP_WORD_ENTRY).l

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
	move.w	#75, 16(a5)
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
	MULTIPART_CHECK_SECTOR mr_stat
	addq.l	#1, (a5)
	addi.l	#0x0800, 8(a5)
	subq.l	#1, 4(a5)
	bne.w	mr_stat
	movem.l	(sp)+, d0-d7/a0-a6
	rts
	.align	2
mr_packet:
	.long	0, 0, 0, 0, 0
multipart_return_image_end:

	.align	2
drv_init_tracklist:
	.byte	1, 0xFF
file_loader_sp:
	.asciz	"PARTSP.BIN"

	.align	2
bios_packet:
	.long	0,0,0,0,0
loader_sp_lba:
	.long	0
loader_sp_sectors:
	.long	0

.global sp_int2
sp_int2:
	rts
.global sp_user
sp_user:
	rts

loader_error:
	move.w #0xDEAD, (COMSTAT0).l
1:
	bra.s 1b

sp_end:
