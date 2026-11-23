.equ STAT_SUB_BOOTED, 0x8008

/* Main BIOS VBlank supplies the Sub BIOS with INT2. Keep it running while
   the Sub BIOS may still be loading the program from the disc. */
.macro wait_sub_boot ready
	cmpi.w	#\ready, (GA_COMSTAT0).l
	beq.s	2f
	move.w	#0x2500, sr
1:
	cmpi.w	#\ready, (GA_COMSTAT0).l
	bne.s	1b
2:
.endm
