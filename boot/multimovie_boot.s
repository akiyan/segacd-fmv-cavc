/* Sega CD boot image for the separate multi-video menu build. */

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
	.ascii "SEGA MEGA DRIVE "
Copyright:
	.ascii "(C) AKIYAN 2026 "
DomesticName:
 .ifdef PLAYLIST
	.ascii "CAVC FMV PLAYLIST"
	.rept 31
	.byte 0x20
	.endr
 .else
	.ascii "CAVC FMV MULTI VIDEO MENU"
	.rept 23
	.byte 0x20
	.endr
 .endif
OverseasName:
 .ifdef PLAYLIST
	.ascii "CAVC FMV PLAYLIST"
	.rept 31
	.byte 0x20
	.endr
 .else
	.ascii "CAVC FMV MULTI VIDEO MENU"
	.rept 23
	.byte 0x20
	.endr
 .endif
ProductCode:
	.ascii "GM 00-0000-00   "
IoSupport:
	.ascii "J               "
	.rept 5
	.ascii "                "
	.endr
Region:
	.ascii "J               "

IPStart:
	.incbin "multimovie_ip.bin"
IPEnd:

	.org 0x6000
SPStart:
	.incbin "multimovie_boot_sp.bin"
SPEnd:

	.align 0x8000
