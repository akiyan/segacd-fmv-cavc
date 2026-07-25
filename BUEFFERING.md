EN / [JP](#jp)

# Pattern Supply and Whole-Movie Quality Planning

This document defines how exact 32-byte tile patterns reach VRAM, how the four
physical pattern supplies differ from the encoder's offline quality budget,
and how boot-only memory is assigned to frames with concentrated exact demand.

## Names

| Public name | Analysis | Memory | Capacity | Lifetime |
|---|---|---|---:|---|
| `PrgBuf` | `Prg` | Sub-CPU PRG-RAM | 12,224 / 12,704 / 12,864 patterns at 15 / 24 / 30 fps (382 / 397 / 402 KiB) | Streamed circular buffer refilled from `BODY.DAT`. |
| `WordBuf0` | `Wr0` | physical 1M Word-RAM bank 0 | 880 patterns / 27.5 KiB | Loaded from `HEADER.DAT`, then consumed by eligible even frames. |
| `WordBuf1` | `Wr1` | physical 1M Word-RAM bank 1 | 880 patterns / 27.5 KiB | Loaded from `HEADER.DAT`, then consumed by eligible odd frames. |
| `DicBuf` | `Dic` | Main RAM | 256 patterns / 8 KiB | Staged through Word RAM at boot, copied to Main RAM, and reused by 8-bit index. |

`PrgBuf` is implemented as a ring buffer, so player assembly uses internal
names such as `RING_BASE` and `RING_SIZE`. `PrgBuf` is the public name of the
pattern supply; `RING_*` describes its data structure.

There is no physical object or analysis meter named Tank. `Buf` is an encoder
funding category for an exact cold load that uses saved quality allowance or a
boot-preload credit. It is not a physical buffer.

## Two Layers

| Layer | Location | Purpose |
|---|---|---|
| whole-movie quality budget | encoder only | Moves permission to spend bytes from light frames to demanding frames. |
| `PrgBuf`, `WordBuf0`, `WordBuf1`, `DicBuf` | player memory | Hold the exact pattern bytes selected for playback. |

The quality budget is accounting, not a fifth player buffer. Its
cadence-specific ceiling equals the normal `PrgBuf` scheduling ceiling so the
encoder cannot assume more time-shifting freedom than the stream can deliver.
The quality-budget and physical-occupancy traces remain different values.

## Objective

The primary quality objective is to avoid concentrating many Miss cells in one
frame. A small approximation distributed across the picture is generally less
damaging than a frame with hundreds of unchanged holes.

The planner prioritizes future changes likely to fall through to Flbk or Miss.
It does not hide starvation by lowering raster size or frame rate.

## End-to-End Planning

Planning runs after palette selection and quantization and before final
per-frame decisions:

1. Render the exact quantized target for every frame.
2. Mark changed cells whose visual difference exceeds the Near bounds. Mark
   every cell at a CRAM segment switch because the switch invalidates every
   live name-table palette reference.
3. Dry-run the complete target through the same `TileAllocator` used by the
   final encode.
4. Record complete exact demand and protected Miss-risk demand per frame.
5. Select reusable `DicBuf` entries, subtract their provisional hits, then
   assign the finite `WordBuf0` and `WordBuf1` credits.
6. Subtract only saved 32-byte pattern payload. Every preloaded exact tile
   still needs its two-byte name-table entry.
7. Start one shared-sector prefix ledger. Before frame `i` makes decisions,
   exact control bytes through frame `i-1` determine frame `i`'s Prg limit.
8. Give frame `i` a matching control-byte ceiling. Reserve one four-byte run
   descriptor per tentative cold choice and commit the exact physical run
   bytes once allocation is known.
9. Walk the adjusted quality demand backwards to build complete-exact and
   protected Miss-risk reserve curves. CRAM-switch name-table bytes are a hard
   floor.
10. Run one stateful encoder pass. It consumes preload credits only for
    selected cold patterns and stays within the Prg, cold, and control limits
    known at the start of each frame.
11. Freeze one physical source for every update in the decision log.
12. Pack and independently replay the frozen assignment. No downstream stage
    may invent a different source choice.

## Demand Prediction

`upgrade_planner.predict_update_demand_details()` advances one shared VRAM
allocator through the exact target. For each timed frame, exact demand contains:

- two bytes for every changed pattern or palette assignment;
- two bytes for every cell at a CRAM segment switch;
- 32 bytes once for every distinct changed pattern that is not resident; and
- a cold-pattern count clipped to the effective cold cap.

Repeated cells sharing one new pattern share its 32-byte cost. A resident exact
pattern costs only the name entry. Frame 0 has no timed-stream demand because
`HEADER.DAT` installs it at boot, but its placement seeds frame 1 residency.

At a palette boundary, the complete name table is mandatory. The previous
indices are rendered through the selected segment palette before visual
distance is measured, so the reserve accounts for the real CRAM change.

| Trace | Includes | Purpose |
|---|---|---|
| complete exact | every exact changed cell and predicted cold pattern | Optional correction of Near, Flbk, Miss, and carried approximations. |
| protected Miss-risk | changed cells beyond the Near bounds | Normal allocation against future Flbk/Miss bursts. |

## Boot-Preload Assignment

`pattern_supply.plan_frame_budgets()` assigns one 32-byte credit at a time.
After each credit it recomputes the affected frame's remaining risk.

Credits are ordered by:

1. protected cold demand before unprotected exact demand;
2. largest remaining protected-byte demand;
3. largest remaining exact-byte and cold demand; and
4. frame number as the deterministic final tie-break.

`DicBuf` entries are selected by whole-movie exact reuse, with protected reuse
as the first tie-break. Dictionary hits do not consume entries. Word RAM is
then assigned under its parity constraint:

- `WordBuf0` serves even timed frames;
- `WordBuf1` serves odd timed frames; and
- frame 0 uses its dedicated boot construction.

The two Word-RAM buffers hold different chronological pattern sequences. They
are not duplicate caches.

## Quality Reserve

Each timed frame receives fresh offline allowance:

```text
frame supply = target bytes per frame
             - audio and fixed control bytes
             - fixed name-table allowance
             - in-stream palette bytes
```

The encoder walks backwards from the movie end:

```text
reserve after frame =
    clamp(next reserve + next demand - next supply,
          0, quality-budget capacity)
```

The final reserve is zero. Light frames before a burst build reserve; a light
tail releases it. Demand larger than the full reserve plus fresh supply is
intentionally clipped and resolved by normal priority, approximation, carry,
and Miss behavior.

The per-frame limit is:

```text
spendable = quality budget before frame
          + fresh frame supply
          - reserve required after frame
```

After the frame:

```text
quality budget after frame =
    clamp(quality budget before frame
          + fresh frame supply
          - actual spending,
          0, quality-budget capacity)
```

Frame 1 starts with the complete quality budget because frame 0 is installed
outside `BODY.DAT`.

## Frozen Physical Sources

Sources are assigned to realized cold updates rather than predicted totals.
A realized key uses `Dic` when present in the dictionary, then consumes the
frame's planned Word credit, and otherwise uses `Prg`. Resident repoints use a
neutral `Prg` source code because they consume no pattern bytes.

The decision log stores source codes aligned with update records. The packer
validates update counts, cold flags, frame-0 rules, preload capacities,
per-frame source totals, and source-aware runs. It materializes:

- the continuously delivered Prg stream;
- the boot-only Wr0 stream;
- the boot-only Wr1 stream; and
- the boot-only indexed DicBuf dictionary.

## Player Path

TTRC v16 carries the source in each cold run descriptor. The descriptor is
authoritative for physical pattern transfer. Source selection changes the
32-byte read address, not the destination VRAM slot or displayed name value.

- `Prg`: Sub consumes the next `PrgBuf` pattern and copies it into the frame's
  Word-RAM output.
- `Wr0` / `Wr1`: Main reads the immutable preload region in the physical bank
  handed over for that frame; frame parity identifies the bank.
- `Dic`: Main addresses the persistent dictionary by 8-bit index.

Word-RAM DMA uses the measured first-word correction. Main-RAM DicBuf DMA does
not. One- and two-tile runs use direct CPU writes; longer runs use bounded
VBlank DMA. A source boundary always splits a run.

## Physical PrgBuf Construction

Only `Prg` loads consume timed payload. The one-pass construction is:

1. `physical_budget.py` tracks cumulative useful route sectors.
2. At frame `i`, exact control through frame `i-1` is rounded to sectors and
   subtracted before calculating the Prg deadline.
3. The resulting Prg prefix sets a strict control-byte ceiling.
4. Exact run bytes are committed after physical slots are known. Savings affect
   frame `i+1` before it makes decisions.
5. Every prefix proves that rounded control through frame `i` plus rounded
   payload needed by frame `i+1` fits the cumulative route.
6. `stream_schedule.py` materializes the split, and
   `pack_stream.py --verify` repeats the proof and trace comparison.

The physical ring is 428 KiB. Normal prebuffer capacity is 382 / 397 / 402 KiB
at 15 / 24 / 30 fps. Scheduled delivery may rise to 422 KiB; the remaining
space is delivery and overflow safety, not feature memory.

## Analysis and Diagnostics

Analysis shows three consumptive remaining-pattern meters and one reusable
dictionary count:

- `Prg` rises with future payload delivery and falls with consumption;
- `Wr0` and `Wr1` start at their actual loaded totals and only fall;
- `Dic` is shown as an installed-entry count because hits do not consume it;
- unloaded preload capacity is not drawn as present data; and
- the quality-budget trace remains diagnostic-only.

`buffer_remaining.npz` schema 6 contains physical remaining amounts, capacities,
realized loads, quality reserve traces, predicted demand, preload credits, and
physical BODY payload/control/pad accounting. The decision log also freezes
`pattern_supply` schema 2, `pattern_transfers` schema 2, and the physical
schedule used by the packer.

## Validation Gates

Every change must pass:

1. allocator, budget, and supply-planner unit tests;
2. sim-to-pack equality for update sources, loads, and run counts;
3. independent replay of every frame and VRAM cell;
4. PrgBuf proof with no underrun or over-cap event;
5. player constants, memory overlap, generated-code, and binary-size checks;
6. a full DEBUG recording with HUD, audio, and visual verification.

## Source Locations

- `tools/upgrade_planner.py`: demand prediction and backwards reserves.
- `tools/physical_budget.py`: shared-sector prefix ledger.
- `tools/pattern_supply.py`: preload allocation and source validation.
- `tools/sim.py`: decisions, source assignment, and frozen logs.
- `tools/pack_stream.py`: serialization and schedule verification.
- `boot/movieplay_sp.s`: boot loading, Prg consumption, and handoff.
- `boot/movieplay_ip.s`: source-aware VRAM transfer.
- `ANALYSIS.md`: meters and timelines.
- `MOVIE.md`: on-disc representation.

---

<a id="jp"></a>

# パターン供給と全編画質計画

この文書は、正確な32-byte tile patternがVRAMへ届く経路、4つの物理pattern供給と
encoder内のoffline画質予算の違い、boot専用memoryを正確な需要が集中するframeへ
割り当てる方法を定義します。

## 名前

| 公開名 | 解析表示 | Memory | 容量 | Lifetime |
|---|---|---|---:|---|
| `PrgBuf` | `Prg` | Sub-CPU PRG-RAM | 15 / 24 / 30 fpsで12,224 / 12,704 / 12,864 pattern（382 / 397 / 402 KiB） | `BODY.DAT`から補充するstreamed circular buffer |
| `WordBuf0` | `Wr0` | physical 1M Word-RAM bank 0 | 880 pattern / 27.5 KiB | `HEADER.DAT`からloadし、対象となるeven frameが消費 |
| `WordBuf1` | `Wr1` | physical 1M Word-RAM bank 1 | 880 pattern / 27.5 KiB | `HEADER.DAT`からloadし、対象となるodd frameが消費 |
| `DicBuf` | `Dic` | Main RAM | 256 pattern / 8 KiB | boot時にWord RAM経由でMain RAMへcopyし、8-bit indexで再利用 |

`PrgBuf`はring bufferとして実装されるため、player assemblyは`RING_BASE`や
`RING_SIZE`などの内部名を使います。Pattern供給の公開名は`PrgBuf`であり、
`RING_*`はdata structureを表します。

Tankという物理objectや解析meterはありません。`Buf`は、保存した画質allowanceまたは
boot-preload creditを使う正確なcold loadのencoder funding categoryであり、
物理bufferではありません。

## 2つのlayer

| Layer | 場所 | 目的 |
|---|---|---|
| 全編画質予算 | encoderのみ | 軽いframeから負荷の高いframeへbyte支出の許可を移動 |
| `PrgBuf`、`WordBuf0`、`WordBuf1`、`DicBuf` | player memory | 再生用に選んだ正確なpattern byteを保持 |

画質予算は会計であり、5つ目のplayer bufferではありません。Cadenceごとのceilingは
通常の`PrgBuf` scheduling ceilingと同じなので、encoderはstreamが配信できる範囲を
超えて時間移動できません。画質予算traceと物理occupancy traceは別の値です。

## 目的

主な画質目的は、多数のMiss cellが1 frameへ集中することを避けることです。画面全体へ
分散した小さな近似は、数百のcellが更新されないframeより一般に目立ちません。

Plannerは、FlbkまたはMissへ落ちやすい将来の変化を優先します。Raster sizeやframe rateを
下げてstarvationを隠しません。

## End-to-end planning

Planningはpalette選択とquantizationの後、最終frame decisionの前に行います。

1. 全frameの正確なquantized targetをrenderします。
2. 見た目の差がNear boundを超えるchanged cellをmarkします。CRAM segment switchでは
   liveなname-table palette referenceがすべて無効になるため、全cellをmarkします。
3. 最終encodeと同じ`TileAllocator`でcomplete targetをdry-runします。
4. Frameごとのcomplete exact demandとprotected Miss-risk demandを記録します。
5. 再利用可能な`DicBuf` entryを選び、その暫定hitを引いてから、有限の`WordBuf0`と
   `WordBuf1` creditを割り当てます。
6. 節約した32-byte pattern payloadだけを引きます。Preload済みexact tileにも
   2-byte name-table entryが必要です。
7. 1つのshared-sector prefix ledgerを開始します。Frame `i`のdecision前に、
   frame `i-1`までのexact control byteからframe `i`のPrg limitを求めます。
8. Frame `i`へ対応するcontrol-byte ceilingを与えます。Tentative cold choiceごとに
   4-byte run descriptorを予約し、allocation確定後にexact physical run byteをcommitします。
9. 調整後のquality demandを後ろ向きに走査し、complete-exactとprotected Miss-riskの
   reserve curveを作ります。CRAM switchのname-table byteはhard floorです。
10. 1回のstateful encoder passを実行します。選ばれたcold patternにだけpreload
    creditを使い、各frame開始時点で既知のPrg、cold、control limitを守ります。
11. 全updateの物理sourceをdecision logへ固定します。
12. 固定assignmentをpackし、独立にreplayします。後工程は別のsource choiceを
    作れません。

## Demand予測

`upgrade_planner.predict_update_demand_details()`は1つのshared VRAM allocatorを
exact target全体で進めます。各timed frameのexact demandには次を含めます。

- patternまたはpalette assignmentが変わるcellごとに2 byte
- CRAM segment switchの全cellに2 byte
- residentでないdistinct changed patternごとに1回だけ32 byte
- effective cold cap以内に制限したcold-pattern数

同じnew patternを共有するcellは32-byte costを共有します。Resident exact patternは
name entryだけを使います。Frame 0はboot時に`HEADER.DAT`がinstallするためtimed-stream
demandを持ちませんが、そのplacementがframe 1のresidencyを初期化します。

Palette boundaryではcomplete name tableが必須です。Visual distanceを測る前に、直前の
indexを選択segment paletteでrenderするため、reserveは実際のCRAM変化を含みます。

| Trace | 内容 | 目的 |
|---|---|---|
| complete exact | 全exact changed cellと予測cold pattern | Near、Flbk、Miss、持越し近似のoptional correction |
| protected Miss-risk | Near boundを超えるchanged cell | 将来のFlbk/Miss burstに対する通常配分 |

## Boot-preload割り当て

`pattern_supply.plan_frame_budgets()`は32-byte creditを1つずつ割り当てます。各creditの
後に、対象frameの残riskを再計算します。

Creditの順序は次のとおりです。

1. unprotected exact demandよりprotected cold demand
2. 残protected-byte demandが最大
3. 残exact-byte demandとcold demandが最大
4. 最後のdeterministic tie-breakとしてframe番号

`DicBuf` entryは全編exact reuseで選び、最初のtie-breakにprotected reuseを使います。
Dictionary hitはentryを消費しません。その後、parity制約付きでWord RAMを割り当てます。

- `WordBuf0`はeven timed frameを供給します。
- `WordBuf1`はodd timed frameを供給します。
- Frame 0は専用boot constructionを使います。

2つのWord-RAM bufferは異なる時系列pattern sequenceを保持し、duplicate cacheでは
ありません。

## 画質reserve

各timed frameは新しいoffline allowanceを受け取ります。

```text
frame supply = frameごとのtarget byte
             - audioとfixed control byte
             - fixed name-table allowance
             - in-stream palette byte
```

Encoderは動画末尾から後ろ向きに走査します。

```text
frame後のreserve =
    clamp(next reserve + next demand - next supply,
          0, quality-budget capacity)
```

最後のreserveは0です。Burst前のlight frameがreserveを作り、軽いtailが解放します。
Full reserveとfresh supplyの合計を超えるdemandは意図的にclipし、通常のpriority、
approximation、carry、Missで解決します。

Frameごとのlimitは次のとおりです。

```text
spendable = frame前のquality budget
          + fresh frame supply
          - frame後に必要なreserve
```

Frame後は次のように更新します。

```text
frame後のquality budget =
    clamp(frame前のquality budget
          + fresh frame supply
          - actual spending,
          0, quality-budget capacity)
```

Frame 0は`BODY.DAT`外でinstallされるため、frame 1はcomplete quality budgetで始まります。

## 固定された物理source

Sourceは予測totalではなく、実際のcold updateへ割り当てます。実keyがdictionaryにあれば
`Dic`を使い、次にそのframeのplanned Word creditを消費し、それ以外は`Prg`を使います。
Resident repointはpattern byteを消費しないため、neutralな`Prg` source codeを持ちます。

Decision logはupdate recordと整列したsource codeを保存します。Packerはupdate count、
cold flag、frame-0 rule、preload capacity、frameごとのsource total、source-aware runを
検証し、次をmaterializeします。

- 連続配信するPrg stream
- boot専用Wr0 stream
- boot専用Wr1 stream
- boot専用indexed DicBuf dictionary

## Player経路

TTRC v16は各cold run descriptorにsourceを持ちます。物理pattern transferではdescriptorが
正本です。Source choiceは32-byte read addressを変えますが、destination VRAM slotや
表示name valueは変えません。

- `Prg`: Subが次の`PrgBuf` patternを消費し、そのframeのWord-RAM outputへcopyします。
- `Wr0` / `Wr1`: Mainが、そのframeでhandoffされたphysical bankのimmutable preload
  regionを読みます。Frame parityがbankを決めます。
- `Dic`: Mainがpersistent dictionaryを8-bit indexで参照します。

Word-RAM DMAは実測済みfirst-word correctionを使います。Main-RAM上のDicBuf DMAには
不要です。1・2 tile runはdirect CPU write、より長いrunはbounded VBlank DMAを使います。
Source境界は必ずrunを分割します。

## 物理PrgBufの構築

Timed payloadを消費するのは`Prg` loadだけです。1-pass構築は次のとおりです。

1. `physical_budget.py`がcumulative useful route sectorを追跡します。
2. Frame `i`では、frame `i-1`までのexact controlをsectorへ丸め、Prg deadline計算前に
   引きます。
3. 得られたPrg prefixがstrict control-byte ceilingを決めます。
4. Physical slot確定後にexact run byteをcommitします。節約分はframe `i+1`のdecision前に
   反映されます。
5. 各prefixは、frame `i`までのrounded controlとframe `i+1`に必要なrounded payloadが
   cumulative routeへ収まることを証明します。
6. `stream_schedule.py`がsplitをmaterializeし、`pack_stream.py --verify`が証明と
   trace比較を繰り返します。

Physical ringは428 KiBです。通常prebuffer capacityは15 / 24 / 30 fpsで
382 / 397 / 402 KiBです。Scheduled deliveryは422 KiBまで使えます。残りはdeliveryと
overflowの安全領域であり、feature memoryではありません。

## 解析とdiagnostic

解析は3つの消費型remaining-pattern meterと、再利用可能なdictionary countを表示します。

- `Prg`は将来payloadの配信で増え、消費で減ります。
- `Wr0`と`Wr1`は実際のload totalから始まり、減少だけします。
- `Dic`はhitで消費しないため、installed-entry countとして表示します。
- Loadしていないpreload capacityをdataが存在するようには表示しません。
- Quality-budget traceはdiagnostic専用です。

`buffer_remaining.npz` schema 6は、物理remaining amount、capacity、realized load、
quality reserve trace、predicted demand、preload credit、物理BODYの
payload/control/pad会計を含みます。Decision logは`pattern_supply` schema 2、
`pattern_transfers` schema 2、packerが使うphysical scheduleも固定します。

## Validation gate

すべての変更で次を通します。

1. allocator、budget、supply-planner unit test
2. update source、load、run countのsim-to-pack一致
3. 全frame・全VRAM cellの独立replay
4. underrunとover-capがないPrgBuf証明
5. player constant、memory overlap、generated code、binary size check
6. HUD、audio、visual verificationを含むfull DEBUG recording

## Source location

- `tools/upgrade_planner.py`: demand predictionとbackwards reserve
- `tools/physical_budget.py`: shared-sector prefix ledger
- `tools/pattern_supply.py`: preload allocationとsource validation
- `tools/sim.py`: decision、source assignment、frozen log
- `tools/pack_stream.py`: serializationとschedule verification
- `boot/movieplay_sp.s`: boot loading、Prg consumption、handoff
- `boot/movieplay_ip.s`: source-aware VRAM transfer
- `ANALYSIS.md`: meterとtimeline
- `MOVIE.md`: disc上の表現
