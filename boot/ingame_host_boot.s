/*
 * Boot sector of the in-game player test disc: the test host's Main IP
 * (with the in-game Main module embedded) and its Sub program.
 *
 * The region-dependent header fields come from disc_region.inc, as for the
 * standalone movie disc.
 */

	.include "disc_region.inc"

DiscHeader:
DiscType:
	.ascii "SEGADISCSYSTEM  "
VolumeName:
	.asciz "SCFMV_GAME "
VolumeSystem:
	.word 0x0100, 0x0001
SystemName:
	.asciz "SEGASYSTEM "
SystemVersion:
	.word 0x0000, 0x0000
IP_Addr:
	.long 0x00000800
IP_Size:
	.long IPEnd-IPStart
IP_Entry:
	.long 0x00000000
IP_WorkRAM:
	.long 0x00000000
SP_Addr:
	.long 0x00006000
SP_Size:
	.long SPEnd-SPStart
SP_Entry:
	.long 0x00000000
SP_WorkRAM:
	.long 0x00000000
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "

HardwareType:
	disc_hardware_type
Copyright:
	.ascii "(C) AKIYAN 2026 "
DomesticName:
	.ascii "SCFMV IN-GAME PLAYER TEST HOST                  "
OverseasName:
	.ascii "SCFMV IN-GAME PLAYER TEST HOST                  "
ProductCode:
	.ascii "GM 00-0000-00   "
IoSupport:
	.ascii "J               "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
	.ascii "                "
Region:
	disc_region_support

	/* Both region fields are fixed-width, so a wrong one would silently
	   push the IP off its sector boundary instead of failing here. */
	.if . - DiscHeader != 0x200
	.error "disc header must be exactly 512 bytes"
	.endif

IPStart:
	.incbin "ingame_host_ip.bin"
IPEnd:

	/* The BIOS can load a multi-sector SP directly. Keep it sector-aligned
	   after the IP and leave the final 8 KiB of the 32 KiB system area for it. */
	.org 0x6000
SPStart:
	.incbin "ingame_host_sp.bin"
SPEnd:

	.align 0x8000
