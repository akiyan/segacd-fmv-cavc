/*
 * cpuvrambench: VBLANK中CPU→VRAM書き実測の Sega CD ブートセクタ。
 * dmabench_boot.s と同レイアウト。IP=cpuvrambench(計測Main), SP=cdcbench_sp(待機)。
 */

DiscHeader:
DiscType:
	.ascii "SEGADISCSYSTEM  "
VolumeName:
	.asciz "SCFMV_CPUVB"
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
	.ascii "SCFMV CPUVRAMBENCH                              "
OverseasName:
	.ascii "SCFMV CPUVRAMBENCH                              "
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
	.incbin "out/cpuvrambench_ip.bin"
IPEnd:

	.org 0x7000
SPStart:
	.incbin "out/cdcbench_sp.bin"
SPEnd:

	.align 0x8000
