/*
 * Sega CD boot sector for the gate-array Font bit expansion benchmark.
 *
 * Same layout as boot.s / cdcbench_boot.s but embeds the fontbench IP/SP.
 */

DiscHeader:
DiscType:
	.ascii "SEGADISCSYSTEM  "
VolumeName:
	.asciz "SCFMV_FNTB "
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
	.long 0x00007000
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
	.ascii "SEGA MEGA DRIVE "
Copyright:
	.ascii "(C) AKIYAN 2026 "
DomesticName:
	.ascii "SCFMV FONT BIT EXPANSION BENCH                  "
OverseasName:
	.ascii "SCFMV FONT BIT EXPANSION BENCH                  "
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
	.ascii "J               "

IPStart:
	.incbin "out/fontbench_ip.bin"
IPEnd:

	.org 0x7000
SPStart:
	.incbin "out/fontbench_sp.bin"
SPEnd:

	.align 0x8000
