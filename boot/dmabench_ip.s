/*
 * dmabench: 表示モード別の VRAM DMA スループット実測(再利用可能)。
 *
 * 1VBLANK で「Main-RAM → VRAM」DMA に何ワード入るかを二分探索で測る。
 * 手順(fits): active→vblank の立ち上がりを待って即 X ワードDMA。DMA完了後に
 * まだ vblank 中なら「その vblank に収まった」。X を二分探索して最大語数を求める。
 * 結果を左上にフォント表示: W=語/vblank F=タイル/コマ(3vblank換算)。
 *
 * RUNS>0 では、Subから1M Word-RAM bankを受け取り、X語をRUNS本の
 * できるだけ均等なrunに分ける。各runはplayerのO_LOADS v2 whole-run経路と
 * 同じpre-swizzled recordをWord RAMからpopし、src+2/full length DMAの後に
 * destination先頭wordをCPUで補修する。REPAIR=0は同じrun分割の補修なし対照。
 * このモードは「追加1runが1VBlankの最大payloadを何word減らすか」を測る。
 *
 * 表示はH40固定(codecの唯一の出力モード)。
 */
.equ VDP_DATA, 0x00C00000
.equ VDP_CTRL, 0x00C00004
.equ GA_COMCMD0, 0x00A12010
.equ GA_COMSTAT0, 0x00A12020
.equ BIOS_LOAD_DEFAULT_VDP_REGS, 0x000002AC
.equ BIOS_CLEAR_VRAM,            0x000002A0
.equ BIOS_VDP_DISP_ENABLE,       0x000002D8
.equ SRC, 0x00FF4000			/* Main-RAM テスト源(内容不問, タイミングのみ) */
.equ WORD_RECORDS, 0x00200000		/* Main所有の1M Word-RAM: 22B/run records */
.equ WORD_SOURCE, 0x00204000		/* 同bank内のlinear test payload */
.equ CMD_GRANT_1M, 0x0043
.equ STAT_DONE, 0x00D0
.equ DMA_DST, 0x2000			/* フォント/NTを壊さない測定用VRAM先 */
.equ DBGFONT_VTILE, 1
.equ DBGFONT_VADDR, 1*32
.equ DBGFONT_N, 16
.equ NT, 0xC000				/* nametable */
.equ HI0, 9000				/* 二分探索上限(理論値を超える値) */
.equ RUN_TICK_PROBE_WORDS, 1024		/* RUNS>0: fixed payload for direct stopwatch slope */
.equ GA_STOPWATCH, 0x00A1200C		/* 12-bit, 30.72us/tick, Main read-only */
.equ FIT_MAX_TICKS, 150			/* DMA開始→完了の上限(4.6ms)。1 vblank(約2.4ms)は
					   余裕で通り、次frameのvblankで完了する巨大DMA
					   (16.7ms級)を弾く。遅延開始計測のwrap誤判定防止 */

.ifndef DELAY_LINES
.equ DELAY_LINES, 0			/* VBlank立ち上がりからDMA開始までの遅延ライン数 */
.endif
.ifndef RUNS
.equ RUNS, 0				/* 0=legacy Main-RAM single DMA; 1..128=Word-RAM runs */
.endif
.ifndef REPAIR
.equ REPAIR, 1				/* RUNS>0: 1=playerの先頭word補修, 0=対照 */
.endif
.if (RUNS < 0) || (RUNS > 128)
	.error "dmabench RUNS must be 0..128"
.endif
.if (REPAIR != 0) && (REPAIR != 1)
	.error "dmabench REPAIR must be 0 or 1"
.endif
.if (RUNS*22) > (WORD_SOURCE-WORD_RECORDS)
	.error "dmabench Word-RAM record table overlaps its payload"
.endif

.text
	.incbin "security.bin"
	bra.w	ip_entry
	.org	0x584

.global ip_entry
ip_entry:
	move.w	#0x2700, sr
	lea	0x00FFFD00, sp
.if RUNS > 0
	bsr	grant_word_ram
	lea	(WORD_SOURCE).l, a0
.else
	lea	(SRC).l, a0
.endif
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
	/* 表示ON + DMA許可 */
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
.if RUNS > 0
	/* Keep W while measuring a direct fixed-payload elapsed time.  This row
	   lets a run-count sweep compare tick/run without converting through DMA
	   word throughput. */
	move.w	d4, -(sp)
	bsr	measure_run_ticks
	move.w	d0, d6			/* E: elapsed 30.72us ticks for 1024 words */
	move.w	(sp)+, d7		/* W */
.else
	move.w	d4, d7			/* W */
.endif
	/* 結果表示はH40 mode5で統一。 */
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
	/* 結果表示。行間はプレーン64幅=128バイト。 */
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
.if RUNS > 0
	/* Row 6: compile-time repaired/unrepaired Word-RAM run count. */
	move.l	#NT+6*128+2*2, d0
	move.w	#RUNS, d4
	bsr	put_row
	/* Row 8: elapsed stopwatch ticks for RUN_TICK_PROBE_WORDS. */
	move.l	#NT+8*128+2*2, d0
	move.w	d6, d4
	bsr	put_row
	/* Keep the proof block separate from the numeric rows. */
	move.l	#NT+10*128+2*2, d0
.else
	/* DMA_DST tile preview: a white block here proves the DMA path wrote VRAM. */
	move.l	#NT+6*128+2*2, d0
.endif
	bsr	set_vram_write
	moveq	#7, d0
1:
	move.w	#(DMA_DST/32), (VDP_DATA).l
	dbra	d0, 1b
hlt:
	bra	hlt

/* d0=語数 → 1vblankに収まるか(d0=1/0)。trashes d0-d2 */
fits:
	movem.l	d3-d7/a0-a3, -(sp)
	move.w	d0, d6				/* words */
.if RUNS > 0
	cmpi.w	#RUNS, d6			/* every configured run must contain >=1 word */
	blo	fits_no
	bsr	build_run_records		/* outside the timed VBlank window */
.endif
1:
	move.w	(VDP_CTRL).l, d0		/* active になるまで */
	btst	#3, d0
	bne	1b
2:
	move.w	(VDP_CTRL).l, d0		/* vblank 立ち上がり */
	btst	#3, d0
	beq	2b
.if DELAY_LINES > 0
	/* VBlank途中開始の検証: 立ち上がりからNライン待ってからDMAを出す。
	   1ライン ≈ 488 cycle @7.67MHz、dbra(taken) 10 cycle → 49回/ライン。 */
	move.w	#DELAY_LINES*49-1, d0
9:
	dbra	d0, 9b
.endif
	move.w	(GA_STOPWATCH).l, d3		/* DMA開始tick */
.if RUNS > 0
	bsr	dma_word_runs			/* pre-swizzled Word-RAM runs */
.else
	move.w	d6, d0
	bsr	dma_words			/* X語DMA(完了待ち) */
.endif
	/* vblankフラグだけでは不十分: 巨大DMAはactiveを跨いで次frameのvblank中に
	   完了し得る(特に遅延開始時)。経過tickで同一vblank内完了を証明する。 */
	move.w	(GA_STOPWATCH).l, d0
	sub.w	d3, d0
	andi.w	#0x0FFF, d0
	cmpi.w	#FIT_MAX_TICKS, d0
	bhi	5f				/* 次frameへwrapした */
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0				/* まだvblank? */
	bne	3f
5:
fits_no:
	moveq	#0, d0				/* はみ出た */
	bra	4f
3:
	moveq	#1, d0
4:
	movem.l	(sp)+, d3-d7/a0-a3
	rts

.if RUNS > 0
/* Ask the shared benchmark Sub program to establish the player's 1M/1M mode
   and return one settled physical bank to Main. */
grant_word_ram:
	clr.w	(GA_COMCMD0).l
1:
	tst.w	(GA_COMSTAT0).l
	bne.s	1b
	move.w	#CMD_GRANT_1M, (GA_COMCMD0).l
2:
	cmpi.w	#STAT_DONE, (GA_COMSTAT0).l
	bne.s	2b
	clr.w	(GA_COMCMD0).l
3:
	tst.w	(GA_COMSTAT0).l
	bne.s	3b
	rts

/* Build RUNS equal-as-possible 22-byte O_LOADS v2 records for d6 total words.
   This happens before the VBlank wait, just as the real Sub pre-swizzles the
   records before Main enters the timed whole-run loop. */
build_run_records:
	move.w	d6, d0
	move.w	#RUNS, d1
	divu.w	d1, d0			/* low=base words/run, high=remainder */
	move.w	d0, d5
	swap	d0
	move.w	d0, d4
	lea	(WORD_RECORDS).l, a0
	lea	(WORD_SOURCE).l, a1
	move.w	#DMA_DST, d7
	move.w	#RUNS-1, d3
1:
	move.w	d5, d6
	tst.w	d4
	beq.s	2f
	addq.w	#1, d6
	subq.w	#1, d4
2:
	move.w	d6, (a0)+		/* +0 len */
	move.w	#0x9300, d0
	move.b	d6, d0
	move.w	d0, (a0)+		/* +2 reg93 */
	move.w	d6, d0
	lsr.w	#8, d0
	ori.w	#0x9400, d0
	move.w	d0, (a0)+		/* +4 reg94 */

	/* +6 ordinary VRAM-write command; Main ORs CD5 into its low word. */
	moveq	#0, d0
	move.w	d7, d0
	move.l	d0, d1
	andi.l	#0x00003FFF, d1
	swap	d1
	ori.l	#0x40000000, d1
	move.l	d0, d2
	lsr.l	#8, d2
	lsr.l	#6, d2
	andi.w	#0x0003, d2
	or.w	d2, d1
	move.l	d1, (a0)+
	move.w	d7, (a0)+		/* +10 raw byte destination */

	/* +12..16 source registers use (src+2)/2, exactly like WordBuf/Prg. */
	move.l	a1, d0
	addq.l	#2, d0
	lsr.l	#1, d0
	move.w	#0x9500, d1
	move.b	d0, d1
	move.w	d1, (a0)+
	lsr.l	#8, d0
	move.w	#0x9600, d1
	move.b	d0, d1
	move.w	d1, (a0)+
	lsr.l	#8, d0
	move.w	#0x9700, d1
	move.b	d0, d1
	move.w	d1, (a0)+
	move.l	a1, (a0)+		/* +18 raw source for first-word repair */

	move.w	d6, d0
	add.w	d0, d0
	adda.w	d0, a1
	add.w	d0, d7
	dbra	d3, 1b
	rts

/* Return the elapsed stopwatch ticks for a fixed 1,024-word transfer. */
measure_run_ticks:
	move.w	#RUN_TICK_PROBE_WORDS, d6
	bsr	build_run_records
1:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	bne.s	1b
2:
	move.w	(VDP_CTRL).l, d0
	btst	#3, d0
	beq.s	2b
.if DELAY_LINES > 0
	move.w	#DELAY_LINES*49-1, d0
3:
	dbra	d0, 3b
.endif
	move.w	(GA_STOPWATCH).l, d3
	bsr	dma_word_runs
	move.w	(GA_STOPWATCH).l, d0
	sub.w	d3, d0
	andi.w	#0x0FFF, d0
	rts

/* Execute the same pre-swizzled whole-run hot path used by the DEBUG player.
   There is deliberately no VBlank refill: fits() decides whether this complete
   RUNS-way transfer remained inside its one starting blank. */
dma_word_runs:
	lea	(WORD_RECORDS).l, a2
	move.w	#RUNS, d4
	move.w	#0x7FFF, d7		/* keep the real whole-run budget branch untaken */
	moveq	#0, d0
	movea.l	d0, a1			/* DEBUG logical-word accumulator */
dma_word_run_loop:
	move.w	(a2)+, d1		/* +0 len */
	move.w	d1, d6
.if REPAIR
	addq.w	#4, d6			/* player's CPU_VDP_WORD_COST accounting */
.endif
	cmp.w	d7, d6
	bls.s	1f
	rts				/* impossible with HI0/RUNS bounds */
1:
	move.w	#0x8F02, (VDP_CTRL).l
	move.w	(a2)+, (VDP_CTRL).l	/* +2 reg93 */
	move.w	(a2)+, (VDP_CTRL).l	/* +4 reg94 */
	move.l	(a2)+, d0		/* +6 ordinary command */
	addq.l	#2, a2			/* skip +10 raw dst */
	move.w	(a2)+, (VDP_CTRL).l	/* +12 reg95 */
	move.w	(a2)+, (VDP_CTRL).l	/* +14 reg96 */
	move.w	(a2)+, (VDP_CTRL).l	/* +16 reg97 */
	move.l	d0, d2
	ori.w	#0x0080, d0
	move.l	d0, (VDP_CTRL).l
	bsr	bench_wait_dma_done
.if REPAIR
	move.l	d2, (VDP_CTRL).l	/* restore ordinary destination */
	movea.l	(a2)+, a3		/* +18 raw Word-RAM source */
	cmpa.l	a2, a3			/* same non-inline branch as a WordBuf run */
	bne.s	2f
	move.w	d1, d0
	add.w	d0, d0
	adda.w	d0, a2
2:
	move.w	(a3), (VDP_DATA).l	/* repair destination word zero */
.else
	addq.l	#4, a2			/* skip +18 raw source in the no-repair control */
.endif
	adda.w	d1, a1			/* match standard DEBUG logical-word accounting */
	sub.w	d6, d7
	bra.w	dma_word_run_done
dma_word_run_done:
	subq.w	#1, d4
	bne	dma_word_run_loop
	rts

bench_wait_dma_done:
1:
	move.w	(VDP_CTRL).l, d0
	btst	#1, d0
	bne.s	1b
	rts
.endif

/* d0=語数を SRC→VRAM tile0 へDMA。完了待ち。trashes d0,d1,d2 */
dma_words:
	move.w	#0x8F02, (VDP_CTRL).l
	move.w	d0, d2
	move.w	#0x9300, d1
	or.b	d2, d1
	move.w	d1, (VDP_CTRL).l
	lsr.w	#8, d2
	move.w	#0x9400, d1
	or.b	d2, d1
	move.w	d1, (VDP_CTRL).l
	move.l	#SRC, d2
	lsr.l	#1, d2
	move.w	#0x9500, d1
	or.b	d2, d1
	move.w	d1, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9600, d1
	or.b	d2, d1
	move.w	d1, (VDP_CTRL).l
	lsr.l	#8, d2
	move.w	#0x9700, d1
	or.b	d2, d1
	move.w	d1, (VDP_CTRL).l
	move.l	#DMA_DST, d2			/* dst コマンド(VRAM書込+CD5起動) */
	move.l	d2, d1
	andi.w	#0x3FFF, d1
	ori.w	#0x4000, d1
	move.w	d1, (VDP_CTRL).l
	move.l	d2, d1
	lsr.l	#8, d1
	lsr.l	#6, d1
	andi.w	#0x0003, d1
	ori.w	#0x0080, d1
	move.w	d1, (VDP_CTRL).l
1:
	move.w	(VDP_CTRL).l, d1
	btst	#1, d1
	bne	1b
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
