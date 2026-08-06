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

Do not put `DEBUG`, `release`, or any other build term in a public title or
description: a viewer does not build this project. A verification upload is
exempt; it keeps the older descriptive title form ending in the build version.

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

## Descriptions come from templates

Descriptions are not written per upload. The wording lives in
`templates/youtube/{analysis,playback,verification}.txt` and only per-video
values are substituted:

```sh
tools/python.sh tools/youtube_description.py --config profiles/PROFILE.toml \
  --kind analysis --timeline-tsv logs/RUN_timeline.tsv \
  --timeline-url GIST --playback-url URL --output DESCRIPTION.txt
```

Every number the renderer substitutes is read from the encode that produced
the video: grid and cell count from the profile, CRAM switches from the sim
decisions, the delivery rate from the analysis TSV, and the build from
`tools/av_version.txt`. Nothing is retyped, so a description cannot carry a
stale figure. An unresolved placeholder is an error, never a blank.

Edit a template when the wording should change, and re-render every affected
description. Do not hand-edit a rendered file: the next render would silently
drop the change.

The templates already encode the rules that used to live here as prose. They
describe the build absolutely rather than as a changelog, they carry no
build-system vocabulary, they name what the RAM is used for instead of the
internal buffer names, and they keep every URL in the English section. A
playback template never mentions analysis panels, because that video has none.

`harness/youtube_description/check_upload_text.py` re-checks a rendered file
before upload. It is a safety net for a hand-edited or legacy description, not
the primary path.

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

公開titleと説明文には`DEBUG`や`release`といったbuildの用語を書きません。視聴者は
このprojectをbuildしません。verification uploadは例外で、build versionを末尾に
置く従来の説明的なtitle形式を保ちます。

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

## 説明文はtemplateから生成する

説明文はuploadごとに書きません。文言は
`templates/youtube/{analysis,playback,verification}.txt` にあり、動画ごとの値
だけを差し込みます:

```sh
tools/python.sh tools/youtube_description.py --config profiles/PROFILE.toml \
  --kind analysis --timeline-tsv logs/RUN_timeline.tsv \
  --timeline-url GIST --playback-url URL --output DESCRIPTION.txt
```

差し込まれる数値はすべて、その動画を作ったencodeから読みます。gridとcell数は
profile、CRAM切り替えはsimのdecisions、配送レートは解析TSV、buildは
`tools/av_version.txt`。手で打ち直す値が無いので、古い数字が残ることがあり
ません。未解決のplaceholderは空文字ではなくerrorになります。

文言を変えるときはtemplateを直し、影響する説明文をすべて生成し直します。
生成済みfileを手で編集しないこと。次の生成で黙って失われます。

かつてここにprose として書いていた規則は、templateが実体として持っています。
changelogではなく絶対的に述べること、buildの用語を持たないこと、内部buffer名
ではなくそのRAMの用途を書くこと、URLを英語節へ集約すること。playback templateは
解析panelに触れません。その動画には無いからです。

upload前に`harness/youtube_description/check_upload_text.py`で再確認します。
これは手編集や過去の説明文に対する安全網であって、主経路ではありません。

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
