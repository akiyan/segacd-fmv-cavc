/* Sega CD boot image for the separate multi-video loader build. */

.include "disc_region.inc"

DiscHeader:
DiscType:
	.ascii "SEGADISCSYSTEM  "
VolumeName:
	.asciz "CAVC_FMV   "
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
	.rept 11
	.ascii "                "
	.endr

HardwareType:
	disc_hardware_type
Copyright:
	.ascii "(C) AKIYAN 2026 "
DomesticName:
	.ascii "CAVC MULTIPART   "
	.rept 31
	.byte 0x20
	.endr
OverseasName:
	.ascii "CAVC MULTIPART   "
	.rept 31
	.byte 0x20
	.endr
ProductCode:
	.ascii "GM 00-0000-00   "
IoSupport:
	.ascii "J               "
	.rept 5
	.ascii "                "
	.endr
Region:
	disc_region_support

IPStart:
	.incbin "multipart_ip.bin"
IPEnd:

	.org 0x6000
SPStart:
	.incbin "multipart_boot_sp.bin"
SPEnd:

	.align 0x8000
