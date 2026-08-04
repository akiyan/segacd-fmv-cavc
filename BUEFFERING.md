EN / [JP](#jp)

# Pattern Supply and Whole-Movie Quality Planning

This document defines how exact 32-byte tile patterns reach VRAM, how the four
physical pattern supplies differ from the encoder's offline quality budget,
and how boot-only memory is assigned to frames with concentrated exact demand.

## Names

| Public name | Analysis | Memory | Capacity | Lifetime |
|---|---|---|---:|---|
| `PrgBuf` | `Prg` | Sub-CPU PRG-RAM | 11,968 / 12,448 / 12,608 patterns at 15 / 24 / 30 fps (374 / 389 / 394 KiB) | Streamed circular buffer refilled from `BODY.DAT`. |
| `WordBuf0` | `Wr0` | frame-0 physical 1M Word-RAM bank | Build-derived, parity-specific | Ring loaded from `HEADER.DAT`, refilled during streaming by leading BODY payload sectors, and consumed by eligible even frames. |
| `WordBuf1` | `Wr1` | other physical 1M Word-RAM bank | Build-derived, parity-specific | Ring loaded from `HEADER.DAT`, refilled during streaming by leading BODY payload sectors, and consumed by eligible odd frames. |
| `DicBuf` | `Dic` | Main RAM | 512 patterns / 16 KiB | Staged through Word RAM at boot, copied to Main RAM, and reused by 9-bit index. |

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
10. At each CRAM switch, inspect the configured short region and select at most
    one frame with the largest positive protected-demand shortage. Lower that
    frame's reserve only by the predicted shortage.
11. Run one stateful encoder pass. It consumes preload credits only for
    selected cold patterns and stays within the Prg, cold, and control limits
    known at the start of each frame.
12. Freeze one physical source for every update in the decision log.
13. Pack and independently replay the frozen assignment. No downstream stage
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

`DicBuf` entries are selected by whole-movie exact reuse, with protected reuse
as the first tie-break. Dictionary hits do not consume entries.

Word RAM uses a lightweight PrgBuf pressure forecast. For each frame, the
forecast subtracts predicted name entries and one identity run descriptor per
cold pattern from the variable BODY allowance. The remaining bytes are
provisional Prg payload supply. Starting with the normal fps-specific PrgBuf
capacity, it accumulates that supply against exact cold demand after DicBuf
hits. The first frame whose predicted balance reaches zero is the pressure
start.

No WordBuf credit is assigned before the pressure start. From that frame,
each physical parity bank water-fills only the pressure suffix. Protected
cold demand is reduced first, followed by complete exact demand. Recomputing
the affected frame after every credit avoids stranding a bank on one
overpredicted frame:

- `WordBuf0` serves even timed frames;
- `WordBuf1` serves odd timed frames; and
- frame 0 uses its dedicated boot construction.

The two Word-RAM buffers hold different chronological pattern sequences. They
are not duplicate caches. The forecast does not run the physical sector
scheduler a second time. The one-pass shared-sector planner still supplies the
authoritative per-frame limits and the final PrgBuf proof.

After credit allocation, the WordBuf ring replan converts each parity plan
into the boot preload plus a timed refill stream. It places the boot turn at
the first pressure suffix, stages refill sectors only where PrgBuf cannot
accept a complete payload sector, assigns only complete physical runs to a
WordBuf source, and the packer's independent replay re-proves every Prg and
WordBuf deadline and capacity for the frozen route.

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

The encoder also finds the first frame from which the strict reserve stays
zero. Fresh allowance left after every predicted demand in that self-funded
suffix is a terminal-drain credit. The credit is available to earlier
Raw/Buf upgrades and shrinks to zero at the final frame. This moves otherwise
stranded tail allowance earlier without changing any physical delivery limit.

The per-frame limit is:

```text
spendable = quality budget before frame
          + fresh frame supply
          - (reserve required after frame - terminal-drain credit)
```

After the frame:

```text
quality balance after frame =
    min(quality-budget capacity,
        quality balance before frame
        + fresh frame supply
        - actual spending)
```

The internal balance may be negative while future suffix allowance is on loan.
The loan must be fully repaid by the final frame or simulation fails.
`quality_budget_remaining` reports only the non-borrowed positive balance;
`quality_budget_balance_bytes` and `quality_budget_debt_bytes` preserve the
signed balance and debt for diagnostics.

Frame 1 starts with the complete quality budget because frame 0 is installed
outside `BODY.DAT`.

At each CRAM switch, the encoder searches a short configurable region starting
at the switch. It selects at most one frame whose predicted protected demand
exceeds fresh frame supply, then lowers that frame's reserve target by exactly
the predicted shortage. A zero-risk region selects nothing. This concentrates
available quality on the single forecast peak without clearing the complete
future reserve or changing any physical delivery limit.

## Frozen Physical Sources

Sources are assigned to realized cold updates rather than predicted totals.
A realized key uses `Dic` when present in the dictionary, then consumes the
frame's planned Word credit, and otherwise uses `Prg`. Resident repoints use a
neutral `Prg` source code because they consume no pattern bytes.

The decision log stores source codes aligned with update records. The packer
validates update counts, cold flags, frame-0 rules, preload capacities,
per-frame source totals, and source-aware runs. It materializes:

- the continuously delivered Prg stream;
- the Wr0 stream, split into its boot preload and its timed ring refill;
- the Wr1 stream, split into its boot preload and its timed ring refill; and
- the boot-only indexed DicBuf dictionary.

## Player Path

The on-disc CAVC layout carries the source in each cold run descriptor. The descriptor is
authoritative for physical pattern transfer. Source selection changes the
32-byte read address, not the destination VRAM slot or displayed name value.

- `Prg`: Sub consumes the next `PrgBuf` pattern and copies it into the frame's
  Word-RAM output.
- `Wr0` / `Wr1`: Main reads the parity WordBuf ring in the physical bank
  handed over for that frame; frame parity identifies the bank. Sub commits
  every timed ring-refill sector before that frame begins expanding, so the
  region Main reads is settled for the whole handoff.
- `Dic`: Main addresses the persistent dictionary by 9-bit index.

Word-RAM DMA uses the measured first-word correction. Main-RAM DicBuf DMA does
not. Every pattern run uses bounded VBlank DMA. A source boundary always
splits a run.

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

The physical ring is 420 KiB. Normal prebuffer and scheduled-delivery capacity
is 374 / 389 / 394 KiB at 15 / 24 / 30 fps. The remaining cadence-specific
headroom up to the 414 KiB observation boundary is reserved for live delivery;
the final 6 KiB is observation and overflow safety, not feature memory.

## Analysis and Diagnostics

Analysis shows three consumptive remaining-pattern meters and one reusable
dictionary count:

- `Prg` rises with future payload delivery and falls with consumption;
- `Wr0` and `Wr1` start at their actual loaded totals and only fall;
- `Dic` is shown as an installed-entry count because hits do not consume it;
- unloaded preload capacity is not drawn as present data; and
- the quality-budget trace remains diagnostic-only.

`buffer_remaining.npz` schema 7 contains physical remaining amounts, capacities,
realized loads, base and effective quality reserve traces, predicted demand,
the terminal-drain start/credit/balance/debt traces, the CRAM-priority frame
mask and shortage, the WordBuf Prg-pressure start and provisional payload
supply, preload credits, and physical BODY payload/control/pad accounting.
The decision log also freezes
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
- `tools/layout_preview.py` and `tools/render_analysis.py`: meters and
  timelines.
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
| `PrgBuf` | `Prg` | Sub-CPU PRG-RAM | 15 / 24 / 30 fpsで11,968 / 12,448 / 12,608 pattern（374 / 389 / 394 KiB） | `BODY.DAT`から補充するstreamed circular buffer |
| `WordBuf0` | `Wr0` | frame-0 physical 1M Word-RAM bank | buildから導出するparity別容量 | `HEADER.DAT`からloadしたringをstream中に先頭BODY payload sectorで補充し、対象となるeven frameが消費 |
| `WordBuf1` | `Wr1` | 反対側のphysical 1M Word-RAM bank | buildから導出するparity別容量 | `HEADER.DAT`からloadしたringをstream中に先頭BODY payload sectorで補充し、対象となるodd frameが消費 |
| `DicBuf` | `Dic` | Main RAM | 512 pattern / 16 KiB | boot時にWord RAM経由でMain RAMへcopyし、9-bit indexで再利用 |

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
10. 各CRAM switchで設定された短い区間を調べ、positiveなprotected-demand不足が
    最大の1 frameだけを選びます。そのframeのreserveを予測不足分だけ減らします。
11. 1回のstateful encoder passを実行します。選ばれたcold patternにだけpreload
    creditを使い、各frame開始時点で既知のPrg、cold、control limitを守ります。
12. 全updateの物理sourceをdecision logへ固定します。
13. 固定assignmentをpackし、独立にreplayします。後工程は別のsource choiceを
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

`DicBuf` entryは全編exact reuseで選び、最初のtie-breakにprotected reuseを使います。
Dictionary hitはentryを消費しません。

Word RAMは軽量なPrgBuf pressure予測を使います。各frameで、variable BODY allowanceから
予測name entryとcold patternごとのidentity run descriptor 1つを引き、残りを暫定Prg
payload供給とします。Fps別のnormal PrgBuf capacityから始め、DicBuf hit後のexact cold
demandに対してこの供給を累積します。予測残高が最初にzeroになるframeがpressure startです。

Pressure startより前にはWordBuf creditを割り当てません。そのframe以降は、各physical
parity bankがpressure suffix内だけをwater-fillします。Protected cold demandを先に減らし、
次にcomplete exact demandを減らします。各credit後に対象frameを再計算するため、予測が
大きすぎた1 frameへbankを固定して使い残すことを避けます。

- `WordBuf0`はeven timed frameを供給します。
- `WordBuf1`はodd timed frameを供給します。
- Frame 0は専用boot constructionを使います。

2つのWord-RAM bufferは異なる時系列pattern sequenceを保持し、duplicate cacheでは
ありません。この予測のためにphysical sector schedulerを2回走らせません。One-pass
shared-sector plannerが、引き続き正本のper-frame limitと最終PrgBuf proofを提供します。

Credit割り当ての後、WordBuf ring replanが各parityの計画をboot preloadとtimed
refill streamへ変換します。boot転回を最初のpressure suffixに置き、PrgBufが完全な
payload sectorを受け取れない場所だけへrefill sectorをstageし、WordBuf sourceには
完全なphysical runだけを割り当てます。packerの独立replayが、凍結routeの全Prg /
WordBuf deadlineとcapacityを再証明します。

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

Encoderは、strict reserveが継続して0になる最初のframeも求めます。そのself-funded suffixで、
全予測demandを払った後に残るfresh allowanceがterminal-drain creditです。このcreditを
前のRaw/Buf格上げで利用し、最終frameへ向けて0まで減らします。物理delivery limitを
変えず、tailで使われないallowanceを前へ移します。

Frameごとのlimitは次のとおりです。

```text
spendable = frame前のquality budget
          + fresh frame supply
          - (frame後に必要なreserve - terminal-drain credit)
```

Frame後は次のように更新します。

```text
frame後のquality balance =
    min(quality-budget capacity,
        frame前のquality balance
        + fresh frame supply
        - actual spending)
```

将来suffixのallowanceを借りている間、internal balanceはnegativeになれます。最終frameまでに
loanを全額返せなければsimは失敗します。`quality_budget_remaining`は借入ではないpositive
balanceだけを示し、`quality_budget_balance_bytes`と`quality_budget_debt_bytes`がsigned
balanceとdebtをdiagnostic用に保持します。

Frame 0は`BODY.DAT`外でinstallされるため、frame 1はcomplete quality budgetで始まります。

各CRAM switchで、encoderはswitch frameから始まる短い設定可能区間を調べます。
予測protected demandがfresh frame supplyを超えるframeを最大1つ選び、そのframeの
reserve targetを予測不足分だけ減らします。Riskがzeroの区間は何も選びません。
将来reserve全体を空にせず、物理delivery limitも変えずに、予測peak 1 frameへ利用可能な
qualityを集中します。

## 固定された物理source

Sourceは予測totalではなく、実際のcold updateへ割り当てます。実keyがdictionaryにあれば
`Dic`を使い、次にそのframeのplanned Word creditを消費し、それ以外は`Prg`を使います。
Resident repointはpattern byteを消費しないため、neutralな`Prg` source codeを持ちます。

Decision logはupdate recordと整列したsource codeを保存します。Packerはupdate count、
cold flag、frame-0 rule、preload capacity、frameごとのsource total、source-aware runを
検証し、次をmaterializeします。

- 連続配信するPrg stream
- boot preloadとtimed ring refillに分かれたWr0 stream
- boot preloadとtimed ring refillに分かれたWr1 stream
- boot専用indexed DicBuf dictionary

## Player経路

On-disc CAVC layoutは各cold run descriptorにsourceを持ちます。物理pattern transferではdescriptorが
正本です。Source choiceは32-byte read addressを変えますが、destination VRAM slotや
表示name valueは変えません。

- `Prg`: Subが次の`PrgBuf` patternを消費し、そのframeのWord-RAM outputへcopyします。
- `Wr0` / `Wr1`: Mainが、そのframeでhandoffされたphysical bankのparity WordBuf
  ringを読みます。Frame parityがbankを決めます。Subは全timed ring-refill sectorを
  そのframeの展開開始前にcommitするため、Mainが読む領域はhandoff中ずっと確定
  しています。
- `Dic`: Mainがpersistent dictionaryを9-bit indexで参照します。

Word-RAM DMAは実測済みfirst-word correctionを使います。Main-RAM上のDicBuf DMAには
不要です。すべてのpattern runがbounded VBlank DMAを使います。Source境界は必ずrunを
分割します。

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

Physical ringは420 KiBです。通常prebufferとscheduled-delivery capacityは
15 / 24 / 30 fpsで374 / 389 / 394 KiBです。414 KiB観測境界までのcadence別headroomは
live delivery専用で、最後の6 KiBは観測・overflow安全領域です。feature memoryでは
ありません。

## 解析とdiagnostic

解析は3つの消費型remaining-pattern meterと、再利用可能なdictionary countを表示します。

- `Prg`は将来payloadの配信で増え、消費で減ります。
- `Wr0`と`Wr1`は実際のload totalから始まり、減少だけします。
- `Dic`はhitで消費しないため、installed-entry countとして表示します。
- Loadしていないpreload capacityをdataが存在するようには表示しません。
- Quality-budget traceはdiagnostic専用です。

`buffer_remaining.npz` schema 7は、物理remaining amount、capacity、realized load、
base/effective quality reserve trace、predicted demand、terminal-drainの
start/credit/balance/debt trace、CRAM-priority frame maskと予測不足量、WordBufの
Prg-pressure startと暫定payload供給、preload credit、物理BODYのpayload/control/pad
会計を含みます。
Decision logは`pattern_supply` schema 2、
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
- `tools/layout_preview.py`と`tools/render_analysis.py`: meterとtimeline
- `MOVIE.md`: disc上の表現
