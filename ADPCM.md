EN / [JP](#jp)

# 22.05 kHz IMA ADPCM playback

The on-disc CAVC layout uses 22.05 kHz mono IMA ADPCM as its only audio format. The Sub CPU
decodes each timed control chunk and writes the reconstructed 8-bit
sign-magnitude samples to the RF5C164.

The 68000-only decode design lacks enough end-to-end streaming margin. The Z80
design requires the Main CPU to stop the Z80 through BUSREQ for every refill,
and that feeding contention produces periodic audio artifacts. The supported
player therefore keeps decode and RF5C164 output on the Sub CPU.

## Format and codec

- Source audio is extracted as 22,050 Hz mono signed 16-bit PCM.
- The packer evenly retimes it to one fixed, even decoded-sample count per
  playback frame.
- IMA state is continuous across the movie. Every frame begins with a four-byte
  checkpoint: signed 16-bit predictor, 8-bit step index, and a reserved zero
  byte. A chunk can therefore be decoded independently after a seek or
  control-ring recovery.
- Two samples are packed per byte, low nibble first.
- The untimed `BODY.DAT` arm audio is already reconstructed RF5C164 data, one
  chunk per sector. Timed control blocks carry future checkpointed ADPCM
  chunks so the wave-RAM write reserve remains persistent.
- Header offset 52 is the decoded RF5C164 sample count per frame. The control
  size is `4 + decoded_samples / 2`.
- Header offset 56 stores the RF5C164 frequency delta calculated from the fixed
  chunk size and actual playback cadence.

The encoder and independent reference decoder are in `tools/ima_adpcm.py`.
`tools/pack_stream.py --verify` reconstructs every audio chunk and proves that
the startup prefix plus shifted controls reproduce the source chunk order for
the complete movie.

The sim analysis and straight sim video use the same shared encode/decode path.
Their waveform and muxed audio therefore contain the reconstructed IMA signal
after RF5C164 8-bit conversion, rather than the clean signed-16 source WAV.
The preview WAV is timed at one decoded chunk per source-video frame; the
physical player uses the header's RF5C164 frequency delta and the actual NTSC
playback cadence.

## Sub PRG-RAM lookup tables

The decoder uses one 8,800-byte full table image:

| Table | Size | Contents |
|---|---:|---|
| next index | 2,848 B | 89 step rows x 16 nibbles, stored as `new_index * 32` |
| signed delta | 5,696 B | 89 x 16 precomputed signed 32-bit predictor deltas |
| output conversion | 256 B | reconstructed predictor high byte to RF5C164 byte |

The image remains stored once on disc after the boot stage. The packer places
the one-shot Sub extension in the otherwise-unused padding after those 8,800
bytes, without adding a sector. At boot the Sub CPU stages the five sectors in
PRG-RAM. It copies the next-index table to `0x07400..0x07F1F`, the output table
to `0x09600..0x096FF`, and the signed deltas to `0x0C000..0x0D63F`. All three
tables are installed once in Sub-owned memory, so no duplicate lookup-table
reservation remains in either physical Word-RAM bank.

The live decoded output buffer occupies Sub PRG-RAM
`0x08000..0x085FF`. Its 1,536 bytes hold the supported low-rate chunk maximum.
The 940-byte boot-only extension is staged at
`0x7D260..0x7D60B` after the lookup data. Its qualified 88-byte table-copy entry is
copied to the unused timed-ring tail at `0x76800..0x76857` and executed before
the routing preload. For a routing table of 8 KiB or less, the fixed second
entry remains beyond the staged routing bytes and executes in place at
`0x7D2B8` after prebuffer completes. Longer-route builds copy the complete
extension first and execute the second entry at `0x76858`. That entry validates
and duplicates the routing table in both Word-RAM banks. A third fixed entry at
extension offset `+0x300` runs in place at `0x7D560` to clear wave RAM and
initialize the RF5C164 channel. The resident Sub image occupies the checked
5 KiB `0x06000..0x073FF` range. The 420 KiB physical PrgBuf begins at the next
sector boundary after the delta table, `0x0D800`.

The build checks bind the full, index/output, and delta table SHA-256 values; the
extension size, CRC-32, preload and execute addresses; its fit in the existing
five-sector padding; the 5 KiB resident BIOS module; and every PRG/Word-RAM
overlap. These reservations are not feature memory.

## Sub-CPU hot path

Once the current control block is linear in Word RAM, the player:

1. loads the checkpoint;
2. reads next-index values and signed deltas from Sub PRG-RAM;
3. converts each reconstructed sample through the output lookup table;
4. sends the decoded buffer through the batched RF5C164 writer; and
5. continues with bitmap and cold-pattern expansion.

At low frame rates one decode chunk can run longer than a CD-sector interval.
The low-rate decoder therefore performs a non-blocking CDC poll at most every
512 packed bytes. Higher-rate specialized builds omit this polling counter and
call from the decode loop.

No inter-frame codec state is carried in PRG-RAM; the decoded output buffer is
overwritten for every chunk. A malformed step index is clamped to 88, and the
fixed chunk size bounds every table and output-buffer access.

The DEBUG `adpcm_decode_units` field measures the decode phase, including an opportunistic
CDC pump on low-rate profiles. One displayed unit is four 30.72 microsecond
Mega-CD stopwatch ticks, about 0.1229 ms.

## Qualification scope

The codec implementation, complete-stream reconstruction, player build matrix,
and emulator recording gate are part of the normal `/run` workflow. Physical
Mega-CD playback and additional cadence combinations remain
broader portability checks rather than alternate-codec fallbacks.

---

<a id="jp"></a>

# 22.05 kHz IMA ADPCM再生

On-disc CAVC layoutの音声形式は、22.05 kHz mono IMA ADPCMのみです。Sub CPUが時刻指定された
各control chunkをdecodeし、復元した8-bit sign-magnitude sampleをRF5C164へ
書き込みます。

68000だけでdecodeする設計には、streaming全体で十分な余裕がありません。Z80を使う
設計では、refillのたびにMain CPUがBUSREQでZ80を停止する必要があり、その供給競合に
よって周期的な音声artifactが生じます。このため、対応playerはdecodeとRF5C164出力を
Sub CPU上で行います。

## Formatとcodec

- Source音声は22,050 Hz mono signed 16-bit PCMとして抽出します。
- Packerは、playback frameごとに固定かつ偶数のdecode sample数となるよう均等に
  retimeします。
- IMA stateは動画全体で連続します。各frameの先頭には4-byte checkpoint
  （signed 16-bit predictor、8-bit step index、予約済みzero byte）を置きます。
  そのため、seekやcontrol-ring recoveryの後でもchunkを独立してdecodeできます。
- 1 byteに2 sampleを格納し、low nibbleを先に置きます。
- untimed `BODY.DAT` armのaudioは、すでに復元済みのRF5C164 dataで、1 sectorに
  1 chunkを格納します。時刻指定control blockには将来分のcheckpoint付きADPCM
  chunkを格納し、wave-RAM write reserveを維持します。
- Header offset 52は、frameごとのdecode済みRF5C164 sample数です。control sizeは
  `4 + decoded_samples / 2`で求めます。
- Header offset 56は、固定chunk sizeと実際のplayback cadenceから求めたRF5C164
  frequency deltaを格納します。

Encoderと独立reference decoderは`tools/ima_adpcm.py`にあります。
`tools/pack_stream.py --verify`は全audio chunkを復元し、startup prefixと
shift済みcontrolが動画全体でsource chunk順を再現することを証明します。

Sim解析とstraight sim videoも同じencode/decode経路を使います。このため、waveformと
mux済み音声には、cleanなsigned-16 source WAVではなく、RF5C164の8-bit変換後に
復元されたIMA信号が入ります。Preview WAVはsource-video frameごとに1 decode chunkの
時間で作られます。物理playerはheaderのRF5C164 frequency deltaと実際のNTSC playback
cadenceを使います。

## Sub PRG-RAM lookup table

Decoderは8,800-byteのfull table imageを1つ使います。

| Table | Size | 内容 |
|---|---:|---|
| next index | 2,848 B | 89 step row x 16 nibble。`new_index * 32`として格納 |
| signed delta | 5,696 B | 89 x 16の事前計算済みsigned 32-bit predictor delta |
| output conversion | 256 B | 復元predictorのhigh byteからRF5C164 byteへの変換 |

Imageはboot stageの後にdisc上へ1つ格納したままです。Packerは8,800 byteの後にある
未使用paddingへone-shot Sub extensionを配置し、sectorは追加しません。Boot時に
Sub CPUが5 sectorをPRG-RAMへstageし、next-index tableを`0x07400..0x07F1F`、
output tableを`0x09600..0x096FF`、signed deltaを`0x0C000..0x0D63F`へcopyします。
3つともSub所有memoryへ1回だけinstallし、physical Word-RAM bankには重複した
lookup-table予約を残しません。

Liveのdecode済みoutput bufferはSub PRG-RAM `0x08000..0x085FF`を使います。1,536 byteで
対応するlow-rate chunkの最大値を収容します。940-byteのboot-only extensionは
lookup data直後の`0x7D260..0x7D60B`へstageします。Qualified済み88-byte table-copy入口だけを
未使用timed-ring tailの`0x76800..0x76857`へcopyし、routing preload前に実行します。
Routing tableが8 KiB以下なら、固定第2入口はstaged routingの後ろに残るため、
prebuffer完了後に`0x7D2B8`でそのまま実行します。長いroutingのbuildだけはextension
全体を先にcopyし、第2入口を`0x76858`で実行します。この入口がrouting tableを
validateして両Word-RAM bankへ複製します。Extension offset `+0x300`の固定第3入口は
`0x7D560`で実行し、wave RAM clearとRF5C164 channel初期化を行います。Resident Sub
imageは検査済み5 KiB `0x06000..0x073FF`を使います。420 KiB physical PrgBufは
delta table直後のsector境界`0x0D800`から始まります。

Build checkはfull・index/output・delta tableのSHA-256、extensionのsize・CRC-32・load/execute
address、既存5-sector paddingへの収容、5 KiB resident BIOS module、全PRG/Word-RAM overlapを固定します。
これらの予約はfeature memoryではありません。

## Sub-CPU hot path

現在のcontrol blockがWord RAM上でlinearになった後、playerは次を行います。

1. checkpointを読み込みます。
2. next-indexとsigned deltaをSub PRG-RAMから読んでdecodeします。
3. 復元した各sampleをoutput lookup tableで変換します。
4. decode済みbufferをbatched RF5C164 writerへ送ります。
5. bitmapとcold-patternの展開を続けます。

低frame rateでは、1 decode chunkの処理がCD-sector intervalより長くなる場合があります。
Low-rate decoderは、packed data 512 byteごとを上限にnon-blocking CDC pollを行います。
高rate向けspecialized buildは、このpolling counterとdecode loopからのcallを省きます。

Frame間codec stateはPRG-RAMに保持せず、decode済みoutput bufferはchunkごとに
上書きします。不正なstep indexは88へclampし、固定chunk sizeによって全table accessと
output-buffer accessを範囲内に保ちます。

DEBUG HUDの`adpcm_decode_units` fieldは、low-rate profileでのopportunistic CDC pumpを含むdecode phaseを
計測します。表示1 unitはMega-CD stopwatchの30.72 microsecond tick 4個分、約0.1229 ms
です。

## Qualification範囲

Codec実装、全stream復元、player build matrix、emulator recording gateは通常の
`/run` workflowに含まれます。物理Mega-CD再生と追加のcadenceの組み合わせは、
別codecへのfallbackではなく、より広いportability checkです。
