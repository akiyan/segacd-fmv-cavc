/*
 * cpuvrambench: VBLANK 中の CPU→VRAM data port 書き込みスループット実測(再利用可能)。
 *
 * 1VBLANK で「Main-RAM → VRAM」CPU 書き込みに何ワード入るかを二分探索で測る。
 * 手順(fits): active→vblank の立ち上がりを待って書込コマンド設定後、X ワードを
 * move.l (a0)+,(VDP_DATA).l の 8 ワードブロック + move.w 端数(player の bf_bw /
 * bf_bword と同形)で書く。書き終わりがまだ vblank 中なら「その vblank に収まった」。
 * 結果を左上にフォント表示: W=語/vblank F=タイル/コマ(3vblank換算)。
 * dmabench の同モード W との比が実測 CPU_VDP_WORD_COST になる。
 *
 * active 中は測らない: VDP FIFO は 4 ワード深で、active 中の CPU 書きは即
 * FIFO 待ちになるため budget 設計の対象にしない。
 *
 * 表示はH40固定(codecの唯一の出力モード)。
 */
.equ VDP_DATA, 0x00C00000
.equ VDP_CTRL, 0x00C00004
.equ BIOS_LOAD_DEFAULT_VDP_REGS, 0x000002AC
.equ BIOS_CLEAR_VRAM,            0x000002A0
.equ SRC, 0x00FF4000			/* Main-RAM テスト源(内容は白 0xFFFF, タイミングのみ) */
.equ CPU_DST, 0x2000			/* フォント/NTを壊さない測定用VRAM先 */
.equ DBGFONT_VTILE, 1
.equ DBGFONT_VADDR, 1*32
.equ DBGFONT_N, 16
.equ NT, 0xC000				/* nametable */
.equ HI0, 4096				/* 二分探索上限(理論上限 ~1.2k 語の3倍超) */

.text
	.incbin "security.bin"
	bra.w	ip_entry
	.org	0x584

.global ip_entry
ip_entry:
	move.w	#0x2700, sr
	lea	0x00FFFD00, sp
	lea	(SRC).l, a0
	move.w	#HI0-1, d0
	move.w	#0xFFFF, d1
1:
	move.w	d1, (a0)+
	dbra	d0, 1b
	jsr	BIOS_LOAD_DEFAULT_VDP_REGS
	jsr	BIOS_CLEAR_VRAM
	/* 表示モード。BIOS_VDP_DISP_ENABLE は reg1 を戻し得るので使わない。 */
	move.w	#0x8C81, (VDP_CTRL).l		/* reg12 H40 */
	move.w	#0x8F02, (VDP_CTRL).l		/* autoinc 2 */
	move.w	#0x9001, (VDP_CTRL).l		/* plane 64x32 */
	move.w	#0x8230, (VDP_CTRL).l		/* reg2 plane A = 0xC000 */
	/* CRAM: index0=黒, index1=白 */
	move.l	#0xC0000000, (VDP_CTRL).l
	move.w	#0x0000, (VDP_DATA).l
	moveq	#14, d0
1:
	move.w	#0x0EEE, (VDP_DATA).l
	dbra	d0, 1b
	/* フォントを VRAM tile1 へ */
	move.l	#(0x40000000|((DBGFONT_VADDR&0x3FFF)<<16)|(((DBGFONT_VADDR>>14)&3))), (VDP_CTRL).l
	lea	dbgfont, a0
	move.w	#DBGFONT_N*16-1, d1
1:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d1, 1b
	/* 表示ON。CPU 書きに DMA 許可は不要だが player と同じ reg1 値で揃える。 */
	move.w	#0x8174, (VDP_CTRL).l		/* reg1: disp on+vint+DMA+M5 */

	/* 二分探索: lo=収まる最大, hi=収まらない最小 */
	moveq	#0, d4				/* lo */
	move.w	#HI0, d5			/* hi */
bs_loop:
	move.w	d5, d0
	sub.w	d4, d0
	cmp.w	#8, d0
	bls	bs_done
	move.w	d4, d0
	add.w	d5, d0
	lsr.w	#1, d0				/* mid */
	move.w	d0, d6				/* keep mid */
	bsr	fits				/* d0=1 fits / 0 not */
	tst.w	d0
	beq	1f
	move.w	d6, d4				/* fits -> lo=mid */
	bra	bs_loop
1:
	move.w	d6, d5				/* not -> hi=mid */
	bra	bs_loop
bs_done:
	/* 結果表示もH40 mode5で統一(dmabenchと同じ結果画面)。 */
	move.w	#0x8004, (VDP_CTRL).l
	move.w	#0x8174, (VDP_CTRL).l
	move.w	#0x8C81, (VDP_CTRL).l
	move.w	#0x9001, (VDP_CTRL).l
	move.w	#0x8230, (VDP_CTRL).l
	move.w	#0x8F02, (VDP_CTRL).l
	move.l	#0x40000000, (VDP_CTRL).l
	moveq	#15, d0
1:
	move.w	#0x0000, (VDP_DATA).l
	dbra	d0, 1b
	move.l	#0xC0000000, (VDP_CTRL).l
	move.w	#0x0000, (VDP_DATA).l
	moveq	#14, d0
1:
	move.w	#0x0EEE, (VDP_DATA).l
	dbra	d0, 1b
	move.l	#(0x40000000|((DBGFONT_VADDR&0x3FFF)<<16)|(((DBGFONT_VADDR>>14)&3))), (VDP_CTRL).l
	lea	dbgfont, a0
	move.w	#DBGFONT_N*16-1, d1
1:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d1, 1b
	move.l	#NT, d0
	bsr	set_vram_write
	move.w	#64*32-1, d0
1:
	move.w	#0x0000, (VDP_DATA).l
	dbra	d0, 1b
	/* 結果表示: d4 = 最大語/vblank。行間はプレーン64幅=128バイト。 */
	move.w	d4, d7				/* W */
	/* Row 2: maximum words per VBlank, four hexadecimal digits. */
	move.l	#NT+2*128+2*2, d0
	move.w	d7, d4
	bsr	put_row
	/* Row 4: tiles per frame at three VBlanks, four hexadecimal digits. */
	move.l	#NT+4*128+2*2, d0
	move.w	d7, d4
	lsr.w	#4, d4				/* /16 = タイル/vblank */
	move.w	d4, d1
	add.w	d1, d1
	add.w	d1, d4				/* *3 */
	bsr	put_row
	/* CPU_DST tile preview: a white block here proves the CPU path wrote VRAM. */
	move.l	#NT+6*128+2*2, d0
	bsr	set_vram_write
	moveq	#7, d0
1:
	move.w	#(CPU_DST/32), (VDP_DATA).l
	dbra	d0, 1b
hlt:
	bra	hlt

/* d0=語数 → 1vblankに収まるか(d0=1/0)。trashes d0-d2/a0 */
fits:
	movem.l	d3/d6, -(sp)
	move.w	d0, d6				/* words */
	lea	(SRC).l, a0
1:
	move.w	(VDP_CTRL).l, d0		/* active になるまで */
	btst	#3, d0
	bne	1b
2:
	move.w	(VDP_CTRL).l, d0		/* vblank 立ち上がり */
	btst	#3, d0
	beq	2b
	move.l	#CPU_DST, d0			/* 書込コマンドも vblank 窓内で設定 */
	bsr	set_vram_write
	/* player の実経路と同形: move.l 4本=8語/ブロック + move.w 端数。 */
	move.w	d6, d1
	lsr.w	#3, d1				/* 8語ブロック数 */
	beq	4f
	subq.w	#1, d1
3:
	move.l	(a0)+, (VDP_DATA).l
	move.l	(a0)+, (VDP_DATA).l
	move.l	(a0)+, (VDP_DATA).l
	move.l	(a0)+, (VDP_DATA).l
	dbra	d1, 3b
4:
	move.w	d6, d1
	andi.w	#7, d1
	beq	6f
	subq.w	#1, d1
5:
	move.w	(a0)+, (VDP_DATA).l
	dbra	d1, 5b
6:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0				/* まだvblank? */
	bne	7f
	moveq	#0, d0				/* はみ出た */
	bra	8f
7:
	moveq	#1, d0
8:
	movem.l	(sp)+, d3/d6
	rts

/* d0=NT address, d4=hex4 value. trashes d0,d1,d2 */
put_row:
	bsr	set_vram_write
	moveq	#3, d2
1:
	rol.w	#4, d4
	move.w	d4, d1
	andi.w	#0xF, d1
	add.w	#DBGFONT_VTILE, d1
	move.w	d1, (VDP_DATA).l
	dbra	d2, 1b
	rts

/* d0=VRAMアドレス → 書込コマンド。trashes d0,d2 */
set_vram_write:
	move.l	d0, d2
	andi.l	#0x3FFF, d0
	swap	d0
	ori.l	#0x40000000, d0
	lsr.w	#7, d2
	lsr.w	#7, d2
	andi.w	#3, d2
	or.w	d2, d0
	move.l	d0, (VDP_CTRL).l
	rts

	.align 2
dbgfont:
	.incbin "dbgfont.bin"
