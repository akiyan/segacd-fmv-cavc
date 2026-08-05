# YouTube Upload Style

Every codec video published from this repository — the analysis render and the
playback recording alike — uses the title, description, privacy, and category
rules below. This document is the only source of truth for that metadata; no
skill restates it.

## Privacy and category

Uploads are unlisted, category 20 (Gaming). Titles are descriptive, never a
sequence number such as `vNNN`. Do not generate YouTube chapters and do not put
timestamp links in a description: these uploads carry no chapter list at all,
at CRAM switch points or anywhere else.

"Upload" always means the latest version. Before uploading, rebuild the
artifact from the current code and data, re-encoding or re-rendering if
anything changed since it was last made; never upload a stale file. A
re-upload of the same artifact uses `--force`, and the previous video stays
unlisted.

## Title

English, fixed format `SEGA-CD FMV of <work> - <specs> <ver>`.

- `<work>`: the work name. For a native or kanji title, give the
  transliteration followed by the native title in parentheses, e.g.
  `Romaji (native)`. A romaji-only work needs no parentheses.
- `<specs>`: the descriptive spec suffix (mode, resolution/grid, "max
  resolution", and so on). No sequence version numbers.
- `<ver>`: the encoder/player build version `YYYYMMDD.eN.pM`, read from
  `tools/av_version.txt`. `e` is the shared encoder implementation and defaults
  (`sim.py` / `pack_stream.py`); `p` is the shared player implementation
  (`boot/movieplay_*.s`). Bump `e` or `p` only when that shared side changes in
  a way that can alter its output, and never decrease either. Do not bump `e`
  for a source-specific profile edit such as its input, trim, geometry, frame
  rate, cold cap, or another encoder setting; the profile/settings identity
  tracks those. Likewise do not bump `p` merely because a different profile or
  stream is played. When bumping, set the date to today if it differs. This is
  the title build version only; the on-disc `HEADER.DAT` layout has no
  independent version field. Update `tools/av_version.txt` whenever you bump.
- Example: `SEGA-CD FMV of Some Work - max resolution 320x224/40x28
  20260710.e1.p1`.

YouTube truncates a title at 100 characters. Measure the title before
uploading and shorten the spec suffix, not the version, when it does not fit:
losing `eN.pM` removes the only record of which build the video shows.

## Description language and links

Write English first, then the same content in Japanese after it. URLs appear
only once, in the English section — a URL is not language specific, so
repeating it in the Japanese half adds nothing. This covers every link: the
project link, timeline links, and cross-links to related uploads all sit at the
end of the English section.

Always include the source repository URL
`https://github.com/akiyan/segacd-fmv-cavc`.

Never put `<` or `>` in a description. YouTube rejects them with
`invalidDescription` (HTTP 400). Write "0.3s or more" or "within 4s" instead.

Save the exact description to a UTF-8 text file and measure its Python
character count before uploading. The limit is 5,000 characters; target 4,800
or fewer and hard-fail above 5,000. When it is too long, shorten explanatory
prose. Never drop the CRAM switch count, the specs, the layout reading guide,
the encoder-technique section, the project link, or the current timeline links.

## Write absolutely, never as a changelog

Each description stands alone as a statement of what this build is and does, as
though it were the only description ever written. Do not compare the video to
an earlier upload, do not say what changed, improved, regressed, or was fixed,
and do not put a build revision in the prose. "Now", "no longer", "previously",
"instead of before", "this version adds", and measured before/after pairs
belong to development notes; the title's `<ver>` is the only place a build
revision appears. When a technique exists because of a hardware constraint,
state the constraint and the resulting behavior, not the history of arriving at
it. A reader who has seen no other video in the series must still understand
the whole picture.

## Explain what a viewer cannot infer from the picture

A viewer sees dithering, a limited palette, a picture that may not fill the
screen, areas that update at different times, and colours that shift at scene
boundaries. Say why each is there: the hardware's 9-bit colour and 4-bit tile
indices, the fixed aperture and per-source raster, the per-frame update budget
under a single-speed CD, and the per-segment CRAM palettes. Prefer naming the
concrete limit over calling something an optimization.

## Description structure

In both languages, in this order:

1. **Introduction** — what the Sega CD Constraint-Aware Video Codec is: full
   motion video that unmodified Sega CD / Mega-CD hardware decodes and displays
   itself while reading one single-speed CD, and what this particular video
   shows. Name the codec **Sega CD Constraint-Aware Video Codec**. Do not use
   the current binary magic as a public codec or format name.
2. **Output and source specs** — the SEGA-CD output (mode, grid WxH, tile
   count, fps, audio, Prg/Wr0/Wr1/Dic capacities, CRAM palette switch count)
   and the Source (resolution, fps, audio). Do not show source bitrate.
3. **How to read the layout** — what each panel, meter, and timeline shows and
   how to interpret it. See "Analysis layout terms" below.
4. **What the encoder does** — a short list of the techniques applied, then the
   detail for each.
5. **Project link** — plus any timeline or cross-upload links, English section
   only.

## CRAM switch count

Every codec video, analysis and playback alike, must state how many times the
palette (CRAM) switches, as part of the output spec section in both languages.
Read the count with `tools/cram_switches.py SIM_OUT`, which prints
`cram_segments=N cram_switches=N-1` from the sim's `frame_seg`. The count
belongs to the encode, so the analysis render and its playback recording report
the same numbers.

## Analysis layout terms

Take every panel, meter, and category name from `tools/layout_preview.py` and
`tools/analysis_style.py` and spell them the same way. Describe an encoder
technique only when `tools/sim.py` still implements it. Do not carry wording
forward from an earlier description without checking it against the current
code; a term that no longer exists in the build must not appear in a new
description.

- Left: the SEGA-CD sim output. Right column: Source, per-tile category map,
  whole-clip category totals, and the 60 fps audio waveform and spectrum.
- Bottom status: Req with its Miss count, Cold, Band, R2V, Run, Prg, Wrd, and
  Pre, then the palette strip and the stacked Req / supply / Run / Band
  timelines.
- Category legend: Raw, Same, Near, Flbk, Miss, Prg, Wrd, Dic. A movie with an
  adopted hardware-scroll window adds Scrl — a cell the active scroll carried
  to its correct position without an update this frame, scroll reuse rather
  than a Miss. Such a movie also shows the legend's right-aligned
  hardware-scroll indicator: green chevrons pointing in the on-screen flow
  direction plus axis:position and speed per frame while a window is active,
  dimmed to "SCROLL ---" between windows. A movie with no adopted window shows
  neither Scrl nor the indicator.
- **Band**: useful `BODY.DAT` payload plus control bytes in the physical
  delivery slot, excluding all pad and the untimed `HEADER.DAT` / BODY-arm /
  frame-0 regions, divided by that slot's actual physical CD read time. Its
  range is 0 to CD 1x (150 KiB/s); pad is unused bandwidth.
- **R2V**: the words the Main CPU moves into VRAM for that frame — pattern
  data, the Word-RAM DMA first-word repair, name-table and HUD words, and
  palette words.
- **Wrd**: the two Word-RAM banks shown as one meter. **Pre**: prefetched cold
  work that is not displayed yet.

---

# YouTube アップロード規約

このリポジトリから公開するcodec動画は、analysis renderもplayback recordingも、
以下のtitle、説明文、公開範囲、categoryの規約に従います。この文書がupload
metadataの唯一の source of truth であり、どのskillもこの内容を再掲しません。

## 公開範囲とcategory

uploadはunlisted、category 20 (Gaming)。titleは内容を述べるもので、`vNNN`の
ような連番は使いません。YouTube chapterは作らず、説明文にtimestampのlinkも
置きません。CRAM切り替え点も含め、これらのuploadはchapter listを一切持ちません。

「upload」は常に最新版を意味します。upload前に現行のcodeとdataから成果物を
作り直し、前回の作成以降に何か変わっていれば再encode・再renderします。古い
fileをuploadしてはいけません。同じ成果物の再uploadは`--force`を使い、前の
動画はunlistedのまま残ります。

## Title

英語、固定形式 `SEGA-CD FMV of <work> - <specs> <ver>`。

- `<work>`: 作品名。native/漢字titleの場合は転写を書き、続けて括弧内へnative
  titleを置きます (例 `Romaji (native)`)。romajiのみの作品に括弧は不要です。
- `<specs>`: 内容を述べるspec接尾辞 (mode、resolution/grid、"max resolution"
  など)。連番versionは使いません。
- `<ver>`: encoder/player build version `YYYYMMDD.eN.pM`。`tools/av_version.txt`
  から読みます。`e`は共有encoder実装と既定値 (`sim.py` / `pack_stream.py`)、
  `p`は共有player実装 (`boot/movieplay_*.s`)。その共有側が出力を変えうる形で
  変化したときだけ`e`か`p`を上げ、どちらも下げません。input、trim、geometry、
  frame rate、cold capなどsource固有のprofile編集で`e`を上げてはいけません。
  それらはprofile/settings identityが追跡します。同様に、別のprofileやstreamを
  再生しただけで`p`を上げません。上げるときは日付が違えば今日にします。これは
  titleのbuild versionのみで、on-discの`HEADER.DAT` layoutは独立したversion
  fieldを持ちません。上げたら`tools/av_version.txt`も更新します。
- 例: `SEGA-CD FMV of Some Work - max resolution 320x224/40x28 20260710.e1.p1`。

YouTubeはtitleを100文字で切ります。upload前にtitle長を測り、収まらないときは
versionではなくspec接尾辞を短くします。`eN.pM`を失うと、その動画がどのbuildの
ものかという唯一の記録が消えます。

## 説明文の言語とlink

英語を先に書き、同じ内容の日本語をその後へ置きます。URLは英語側にのみ1回だけ
置きます。URLは言語に依存しないため、日本語側で繰り返しても何も増えません。
これはproject link、timeline link、関連uploadへのcross-linkのすべてに適用し、
まとめて英語節の末尾へ置きます。

sourceのrepository URL `https://github.com/akiyan/segacd-fmv-cavc` は常に
含めます。

説明文へ`<`と`>`を入れてはいけません。YouTubeが`invalidDescription`
(HTTP 400)で拒否します。「0.3s or more」「within 4s」のように書きます。

送信する説明文はUTF-8 text fileへ保存し、upload前にPythonの文字数で測ります。
上限は5,000文字、運用目標は4,800文字以下で、5,000超はhard failです。長すぎる
ときは説明の散文を短くします。CRAM切り替え回数、spec、layoutの読み方、
encoder技術の節、project link、現行のtimeline linkは削ってはいけません。

## changelogではなく絶対的に書く

各説明文は、それ単体で「このbuildが何であり何をしているか」を述べるもので、
他に説明文が存在しないかのように書きます。前のuploadとの比較、変更点、改善・
後退・修正の記述、そして散文中のbuild revisionを書いてはいけません。「now」
「no longer」「previously」「instead of before」「this version adds」、および
測定値のbefore/after対は開発notesのものです。build revisionはtitleの`<ver>`
だけが持ちます。ある技術がhardware制約ゆえに存在するときは、そこへ至った経緯
ではなく制約と結果の挙動を書きます。このシリーズの他の動画を1本も見ていない
読者が、それだけで全体を理解できなければなりません。

## 一目では分からないことを説明する

視聴者にはdither、限られた色数、画面を埋めないことのある絵、場所によって更新
時期が異なること、場面境界での色の変化が見えます。そのそれぞれについて理由を
書きます: hardwareの9-bit色と4-bit tile index、固定apertureとsourceごとの
raster、単速CD下でのframeあたり更新予算、segmentごとのCRAM palette。何かを
最適化と呼ぶより、具体的な限界を名指しすることを優先します。

## 説明文の構成

英日とも、この順で書きます。

1. **導入** — Sega CD Constraint-Aware Video Codecとは何か。無改造の
   Sega CD / Mega-CD自身が単速CDを読みながらdecodeして表示するfull motion
   videoであること、そしてその動画が何を映しているか。codec名は
   **Sega CD Constraint-Aware Video Codec** とし、現行のbinary magicを公開の
   codec名やformat名として使いません。
2. **出力とsourceのspec** — SEGA-CD出力 (mode、grid WxH、tile数、fps、音声、
   Prg/Wr0/Wr1/Dicの容量、CRAM palette切り替え回数) とSource (解像度、fps、
   音声)。sourceのbitrateは書きません。
3. **layoutの読み方** — 各panel、meter、timelineが何を示し、どう解釈するか。
   下の「解析layoutの用語」を参照します。
4. **encoderの動作** — 適用した技術の短い列挙と、それぞれの詳細。
5. **project link** — timelineやcross-uploadのlinkも含め、英語節のみ。

## CRAM切り替え回数

analysisもplaybackも、すべてのcodec動画は palette (CRAM) が何回切り替わるかを
出力spec節へ英日とも記載します。`tools/cram_switches.py SIM_OUT` で読み、
simの`frame_seg`から`cram_segments=N cram_switches=N-1`を出力します。回数は
encodeの性質なので、analysis renderとそのplayback recordingは同じ値を報告
します。

## 解析layoutの用語

panel、meter、category名はすべて`tools/layout_preview.py`と
`tools/analysis_style.py`から取り、同じ綴りで書きます。encoder技術は
`tools/sim.py`が現に実装しているものだけを書きます。以前の説明文の言い回しを
現行codeと照合せずに持ち越してはいけません。buildに存在しなくなった用語が
新しい説明文へ現れてはなりません。

- 左: SEGA-CD simulation出力。右列: Source、tileごとのcategory map、全編の
  category合計、60 fpsのaudio波形とspectrum。
- 下部status: ReqとそのMiss数、Cold、Band、R2V、Run、Prg、Wrd、Pre、続いて
  palette stripとReq / supply / Run / Bandの積層timeline。
- category legend: Raw、Same、Near、Flbk、Miss、Prg、Wrd、Dic。hardware scroll
  windowを採用した動画はScrlを加えます。これはactiveなscrollが、そのframeでの
  更新なしにcellを正しい位置へ運んだもので、Missではなくscrollの再利用です。
  その動画はlegend右端のhardware scroll indicatorも表示します: window活動中は
  画面上の流れる向きを指す緑のchevronとaxis:position、frameあたりの速度、
  window間は"SCROLL ---"へ落とします。採用windowの無い動画はScrlもindicatorも
  表示しません。
- **Band**: 物理配送slot内の有効な`BODY.DAT` payloadとcontrol byteを、すべての
  padと非計時の`HEADER.DAT` / BODY-arm / frame-0領域を除いて、そのslotの実際の
  物理CD読み取り時間で割った値。範囲は0からCD 1x (150 KiB/s)で、padは使われ
  なかった帯域です。
- **R2V**: そのframeでMain CPUがVRAMへ移すword数 — pattern data、Word-RAM DMA
  の先頭word補修、name-tableとHUDのword、paletteのword。
- **Wrd**: 2つのWord-RAM bankを1つのmeterで表示。**Pre**: まだ表示していない
  先読みのcold work。
