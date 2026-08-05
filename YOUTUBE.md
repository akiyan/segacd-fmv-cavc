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

Titles are authored per source in the profile, not generated from a template:

```toml
[youtube]
analysis_title = "Sega CD FMV at 30 FPS – Work Name Visual Analysis & Encoding Breakdown"
playback_title = "Custom Sega CD FMV Codec Demo – Work Name at 30 FPS"
```

Use those strings verbatim. They are written to be found and understood by
someone who has never heard of this project, so do not append specs, a build
version, or a sequence number to them. `tools/encode_config.py` rejects a title
over 100 characters, the point where YouTube truncates.

A capture that carries the on-screen counter row appends
` (with on-screen counters)` to `playback_title`, so the plain recording keeps
the unmarked public title. Do not put `DEBUG`, `release`, or any other build
term in a title or description: a viewer does not build this project.

Because no version appears in the title, the description's closing line is the
only record of which build a video shows. It is mandatory; see below.

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

Save the exact description to a UTF-8 text file and check it before uploading
with `harness/youtube_description/check_upload_text.py`, which enforces the
mechanical rules in this document. The limit is 5,000 characters; target 4,800
or fewer. When it is too long, shorten explanatory prose. Never drop the CRAM
switch count, the specs, the layout reading guide, the encoder-technique
section, the project link, or the current timeline links.

## Write absolutely, never as a changelog

Each description stands alone as a statement of what this build is and does, as
though it were the only description ever written. Do not compare the video to
an earlier upload, do not say what changed, improved, regressed, or was fixed,
and do not narrate a build revision. "Now", "no longer", "previously",
"instead of before", "this version adds", and measured before/after pairs
belong to development notes. Naming the build the video was made from is not a
changelog: the closing line states it once as a fact. When a technique exists because of a hardware constraint,
state the constraint and the resulting behavior, not the history of arriving at
it. A reader who has seen no other video in the series must still understand
the whole picture.

## Name the constraint, not the optimization

When a technique needs explaining, give the hardware limit that forces it
rather than calling it an optimization. Keep this inside the technique it
belongs to; a standalone tour of the hardware reads as a lecture and is the
first thing to cut when the description runs long. Internal buffer names mean
nothing to a viewer: say what the RAM is used for, not `PrgBuf` or `DicBuf`
with a capacity.

## Video kinds

Two kinds of video are published, and each stands alone. A viewer arriving at
either one gets a complete account of what they are watching; the pair
cross-reference each other as complements, never as a prerequisite.

- **Analysis** — the 1920x1080 render whose frame carries the simulated Sega CD
  output plus the source, category map, meters, and timelines.
- **Playback** — a recording of the codec running, framed exactly as the
  hardware outputs it. It has no analysis panels, no meters, and no timelines.

Never describe analysis panels, meters, timelines, or the category legend in a
playback description. Those elements are not on screen there, so naming them
misleads the viewer. Describe what a playback video actually shows: the
Mega-CD startup, the transition into the movie, the movie itself, and the
on-screen counter row when one is present.

The codec itself — what it is, what it achieves on this hardware, and which
constraints shape the picture — belongs in both kinds.

## Description structure

In both languages, in this order.

Shared by both kinds:

1. **Introduction** — what the Sega CD Constraint-Aware Video Codec is: full
   motion video that unmodified Sega CD / Mega-CD hardware decodes and displays
   itself while reading one single-speed CD, and what this particular video
   shows. Name the codec **Sega CD Constraint-Aware Video Codec**. Do not use
   the current binary magic as a public codec or format name.
2. **Output and source specs** — the SEGA-CD output (mode, grid WxH, tile
   count, fps, audio, Prg/Wr0/Wr1/Dic capacities, CRAM palette switch count)
   and the Source (resolution, fps, audio). Do not show source bitrate.
3. **What the encoder does** — the techniques applied, each stated with the
   hardware constraint that makes it necessary rather than as a separate
   lecture on the hardware.

Analysis only:

4. **How to read the layout** — what each panel, meter, and timeline shows and
   how to interpret it. See "Analysis layout terms" below.

Playback only:

4. **What the recording contains** — that it starts at the emulator launch and
   keeps the Mega-CD startup and CD-player transition before playback begins,
   whether an on-screen counter row is present, and how the native raster was
   enlarged for delivery.

Both kinds end with:

5. **Links** — the project link, the cross-link to the other kind for the same
   encode, and any timeline link. English section only.
6. **Build line** — the last line of the description, in the English section
   only: `Build: YYYYMMDD.eN.pM` read from `tools/av_version.txt`. Since the
   title carries no version, this line is the only way to tell which encoder
   and player produced the video.

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

titleはtemplateから生成せず、sourceごとにprofileへ書きます:

```toml
[youtube]
analysis_title = "Sega CD FMV at 30 FPS – Work Name Visual Analysis & Encoding Breakdown"
playback_title = "Custom Sega CD FMV Codec Demo – Work Name at 30 FPS"
```

その文字列をそのまま使います。このprojectを知らない人に見つけられ、理解される
ことを意図して書かれているので、specやbuild version、連番を後ろへ足しません。
`tools/encode_config.py` は100文字を超えるtitleを拒否します。100文字はYouTubeが
titleを切る位置です。

画面上のカウンタ行が入るcaptureは`playback_title`へ ` (with on-screen counters)`
を足し、素の録画が無印の公開titleを保ちます。titleにも説明文にも`DEBUG`や
`release`といったbuildの用語を書きません。視聴者はこのprojectをbuildしません。

titleにversionが入らないため、説明文末尾の行がその動画のbuildを示す唯一の記録に
なります。必須です。下記を参照してください。

## 説明文の言語とlink

英語を先に書き、同じ内容の日本語をその後へ置きます。URLは英語側にのみ1回だけ
置きます。URLは言語に依存しないため、日本語側で繰り返しても何も増えません。
これはproject link、timeline link、関連uploadへのcross-linkのすべてに適用し、
まとめて英語節の末尾へ置きます。

sourceのrepository URL `https://github.com/akiyan/segacd-fmv-cavc` は常に
含めます。

説明文へ`<`と`>`を入れてはいけません。YouTubeが`invalidDescription`
(HTTP 400)で拒否します。「0.3s or more」「within 4s」のように書きます。

送信する説明文はUTF-8 text fileへ保存し、upload前に
`harness/youtube_description/check_upload_text.py` で検査します。この文書の
機械的に判定できる規則はそこで強制されます。上限は5,000文字、運用目標は
4,800文字以下です。長すぎるときは説明の散文を短くします。CRAM切り替え回数、
spec、layoutの読み方、encoder技術の節、project link、現行のtimeline linkは
削ってはいけません。

## changelogではなく絶対的に書く

各説明文は、それ単体で「このbuildが何であり何をしているか」を述べるもので、
他に説明文が存在しないかのように書きます。前のuploadとの比較、変更点、改善・
後退・修正の記述、そして散文中のbuild revisionを書いてはいけません。「now」
「no longer」「previously」「instead of before」「this version adds」、および
測定値のbefore/after対は開発notesのものです。build revisionを語ってはいけません。動画がどのbuildから作られたかを
書くことはchangelogではなく、最終行がそれを事実として一度だけ述べます。ある技術がhardware制約ゆえに存在するときは、そこへ至った経緯
ではなく制約と結果の挙動を書きます。このシリーズの他の動画を1本も見ていない
読者が、それだけで全体を理解できなければなりません。

## 最適化ではなく制約を名指しする

技術の説明が要るときは、それを最適化と呼ぶのではなく、そうせざるを得ない
hardwareの限界を書きます。説明はその技術の中に収めます。hardwareの解説を
単体で並べると講義になり、説明文が長すぎるときに最初に削る対象になります。
内部のbuffer名は視聴者に何も伝えません。`PrgBuf`や`DicBuf`と容量を並べるので
はなく、そのRAMが何に使われるかを書きます。

## 動画の種類

公開する動画は2種類あり、それぞれ単体で完結します。どちらから来た視聴者も、
今見ているものの説明を一通り得られます。2つは互いを補完するものとして参照
しあいますが、前提条件としては扱いません。

- **Analysis** — 1920x1080のrenderで、frameにSega CD出力のsimulationとsource、
  category map、meter、timelineを持つもの。
- **Playback** — codecの動作をhardwareが出力するそのままの画面で録画したもの。
  解析panelもmeterもtimelineもありません。

playbackの説明文に解析panel、meter、timeline、category legendを書いては
いけません。そこには映っていないので、名前を出すこと自体が視聴者を誤らせます。
playbackで実際に映るもの、すなわちMega-CDの起動画面、映画への遷移、映画本体、
そして在る場合は画面上のカウンタ行を書きます。

codec自体が何であるか、このhardwareで何を成しているか、どの制約が絵を
決めているかは、両方の種類に書きます。

## 説明文の構成

英日とも、この順で書きます。

両方に共通:

1. **導入** — Sega CD Constraint-Aware Video Codecとは何か。無改造の
   Sega CD / Mega-CD自身が単速CDを読みながらdecodeして表示するfull motion
   videoであること、そしてその動画が何を映しているか。codec名は
   **Sega CD Constraint-Aware Video Codec** とし、現行のbinary magicを公開の
   codec名やformat名として使いません。
2. **出力とsourceのspec** — SEGA-CD出力 (mode、grid WxH、tile数、fps、音声、
   Prg/Wr0/Wr1/Dicの容量、CRAM palette切り替え回数) とSource (解像度、fps、
   音声)。sourceのbitrateは書きません。
3. **encoderの動作** — 適用した技術。hardwareの解説を別立てにするのではなく、
   各技術をそれが必要になる制約と一緒に述べます。

Analysisのみ:

4. **layoutの読み方** — 各panel、meter、timelineが何を示し、どう解釈するか。
   下の「解析layoutの用語」を参照します。

Playbackのみ:

4. **録画に何が入っているか** — emulator起動から始まり、再生前のMega-CD起動
   画面とCD playerの遷移を保っていること、画面上のカウンタ行があるかどうか、
   そしてnative rasterを配信用にどう拡大したか。

両方の末尾:

5. **link** — project link、同じencodeのもう一方の種類へのcross-link、そして
   timeline link。英語節のみ。
6. **build行** — 説明文の最終行、英語節のみ: `tools/av_version.txt` から読んだ
   `Build: YYYYMMDD.eN.pM`。titleがversionを持たないため、この行がどのencoderと
   playerで作られた動画かを知る唯一の手段です。

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
