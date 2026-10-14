/* Menu-free dispatcher using the multi-video loader's copy/ACK protocol.
 * Only index/cycle/visit survive a movie. The launcher is reloaded at EOF.
 */
.equ STACK, 0x00FFFD00
.equ VDP_CTRL, 0x00C00004
.equ VDP_DATA, 0x00C00000
.equ BIOS_CLEAR_VRAM, 0x000002A0
.equ BIOS_LOAD_DEFAULT_VDP_REGS, 0x000002AC
.equ GA_COMCMD0, 0x00A12010
.equ GA_COMCMD1, 0x00A12012
.equ GA_COMSTAT0, 0x00A12020
.equ STAT_MENU_READY, 0x8005
.equ STAT_MENU_IP_READY, 0x8006
.equ STAT_PLAYER_READY, 0x8007
.equ CMD_MENU_LOAD, 0x0052
.equ PLAYLIST_STATE, 0x00FFB1D0
.equ PLAYLIST_INDEX, PLAYLIST_STATE+4
.equ PLAYLIST_CYCLE, PLAYLIST_STATE+8
.equ PLAYLIST_VISIT, PLAYLIST_STATE+12
.equ MULTI_LOOP_FLAG_MAIN, 0x00FFB1F0
.equ COPY_STUB, 0x00FF8880
.equ PLAYER_ENTRY, 0x00FF0000
.equ PLAYER_STAGE, 0x00205000

.include "multimovie_ip.inc"
.text
.incbin "security.bin"
	bra.w playlist_first
	.org 0x584

.global playlist_first
playlist_first:
	move.l #0x504C5354, (PLAYLIST_STATE).l
	move.w #-1, (PLAYLIST_INDEX).l
	clr.l (PLAYLIST_CYCLE).l
	clr.l (PLAYLIST_VISIT).l

.global playlist_resume
playlist_resume:
	move.w #0x2700, sr
	lea STACK, sp
	clr.w (MULTI_LOOP_FLAG_MAIN).l
	addq.w #1, (PLAYLIST_INDEX).l
	cmpi.w #MENU_COUNT, (PLAYLIST_INDEX).l
	blo.s 1f
	clr.w (PLAYLIST_INDEX).l
	addq.l #1, (PLAYLIST_CYCLE).l
1:
	addq.l #1, (PLAYLIST_VISIT).l
	jsr BIOS_LOAD_DEFAULT_VDP_REGS
	move.w #0x8134, (VDP_CTRL).l
	move.w #0x8F02, (VDP_CTRL).l
	move.l #0x40000000, (VDP_CTRL).l
/* Observational LOGVDP marker while display/audio are stopped. The following
 * BIOS clear erases these words before any movie is allowed to start. */
.global playlist_trace_begin
playlist_trace_begin:
	move.l #0x504C5354, (VDP_DATA).l
	move.w (PLAYLIST_INDEX).l, (VDP_DATA).l
	move.l (PLAYLIST_CYCLE).l, (VDP_DATA).l
	move.l (PLAYLIST_VISIT).l, (VDP_DATA).l
	move.w #0x454E, (VDP_DATA).l
.global playlist_trace_end
playlist_trace_end:
	jsr BIOS_CLEAR_VRAM
	clr.w (GA_COMCMD0).l
	clr.w (GA_COMCMD1).l
	lea playlist_copy, a0
	lea COPY_STUB.l, a1
	move.w #((playlist_copy_end-playlist_copy)/2)-1, d0
2:
	move.w (a0)+, (a1)+
	dbra d0, 2b
3:
	cmpi.w #STAT_MENU_READY, (GA_COMSTAT0).l
	bne.s 3b
	move.w (PLAYLIST_INDEX).l, d0
	move.w d0, (GA_COMCMD1).l
	move.w #CMD_MENU_LOAD, (GA_COMCMD0).l
4:
	cmpi.w #STAT_MENU_IP_READY, (GA_COMSTAT0).l
	bne.s 4b
	move.w (PLAYLIST_INDEX).l, d0
	add.w d0, d0
	lea menu_ip_sizes, a0
	move.w (a0,d0.w), d1
	add.w d0, d0
	lea playlist_player_entries, a0
	move.l (a0,d0.w), d3
	jmp COPY_STUB.l

/* Executes outside the image being replaced; ACK only after the last word. */
playlist_copy:
	lea PLAYER_STAGE.l, a0
	lea PLAYER_ENTRY.l, a1
	move.w d1, d2
	lsr.w #1, d2
	subq.w #1, d2
1:
	move.w (a0)+, (a1)+
	dbra d2, 1b
	clr.w (GA_COMCMD0).l
2:
	cmpi.w #STAT_PLAYER_READY, (GA_COMSTAT0).l
	bne.s 2b
	movea.l d3, a0
	jmp (a0)
playlist_copy_end:

/* The builder checks the final linked copy length against PLAYLIST_STATE. */
