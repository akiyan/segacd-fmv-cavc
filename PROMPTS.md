EN / [JP](#jp)

# Development Prompt Record

This document keeps verbatim records of representative human prompts sent to
AI assistants during development, with English translations. The prompts are
decisions, verdicts, and findings passed to the assistants; none of them
describe implementation steps.

The Japanese text is authoritative and is never edited. The English text is a
translation only; fix it when it mistranslates the Japanese, never the reverse.

## 1. Palette black handling

In addition to dark specks, bright specks have now become noticeable. Drop the
multi-candidate mixing.

But it made me notice one important fact.

"The black entry that every palette line forcibly carries."

This is itself a distorted palette colour coming from the Mega Drive palette
specification, and it looks like a cause of the current problem. This black
palette is fixed, so it should be treated as an exception. But leaving it
unused would be a waste, so the palette selection algorithm may use it when it
genuinely wants a very deep black. Because it needs it. SonicOP probably is
not asking for it, yet it exists, so it may be getting picked through
two-colour mixing. A very deep black that was not wanted in that 16-colour
(15-colour) palette should be treated as nonexistent as a colour-reproduction
tool.

## 2. Dropping H32 and mode4

H32 has larger dots relative to the screen, and I had hoped that would save
capacity, but the larger dots make dithered expression feel very coarse, so in
the end everything adopted H40. The DMA bandwidth also shrinks, tightening the
cold limit: even though fewer tiles are needed, fewer tiles can be
transferred.

Mode4 also offers only one BG plane plus sprites, with no Window. Using DMA
would require switching between mode4 and mode5 inside VBlank, and exceeding
VBlank must never happen, so considering implementation difficulty and build
branching, I will make this an H40-only codec.

Make the whole codebase H40-only, note briefly in the README that H32 is
unsupported with the reason, and note the H32 removal in REMOVED. mode4 needs
no mention anywhere (remove it if written).

## 3. Real-hardware-only audio noise

I thought issue #81 was done, but noise still rides on the audio constantly on
the real Mega Drive 2 / Mega CD 2. When movie playback ends, the noise stops.
It is not analogue noise but a digital, real-hardware-only problem reaching
the sound source.

Booting the same ISO from a MEGA EVERDRIVE PRO produces no noise at all and
is clean. The MEGA EVERDRIVE PRO carries Mega CD circuitry internally, but its
behavior seems to differ from the real machine. The BIOS used on the MEGA
EVERDRIVE PRO was dumped from this very Mega CD 2, so there is no BIOS
difference either.

I do not want to burn CD-Rs over and over, so I want an accurate fix, looking
up information where needed.

## 4. Withdrawing my own constraint

Generalization to support 15fps is definitely happening, but wait a moment. I
imposed the constraint "use WordBuf first," but that may have been my
mistake. WordBuf is inefficient, so if we schedule it as "use it when PrgBuf
runs out, and refill it when PrgBuf is full," it would serve as a "PrgBuf
backup" and feel less likely to fall back across the whole movie. Also,
instead of "must accumulate refill but overflows if over-accumulated, so NG,"
we could "refill only when there is room to build a delivery schedule that
can refill promptly," making refill happen within possible limits. What do
you think?

## 5. No unplanned rework

Sounds good. Let us refresh the pipeline so that later stages never break
constraints and cause rework. Rework is ad-hoc symptomatic treatment.
"Unplanned rework" is not acceptable. It is big work, but the payoff is big
too. After the pipeline is clean like that, let us add back a step that
reduces run counts as "planned rework" in a set-localiy style.

## 6. Making a principle absolute

$new: Fold the universally usable parts of the earlier findings document into
AGENTS.md (in English). Especially the "**schedules where the average fits
but the deadline is missed**" part matters. In this project every cd1x moment
is constant at every instant, and fitting by average is meaningless. That is
the absolute premise. And

## 7. Carrying in my own analysis

When H40 Bad Apple at cold240 produced SLIP and the HUD gate FAILED, the
following exchange happened.

More like transfer volume crossing the boundary and waiting for the next
VBlank than run fragmentation.
At 30fps one frame can use 2 VBlanks, the first VBLANK and the next VBLANK.
Can the first runs and CPU transfers run before the first VBLANK now? Or,
depending on preprocessing, could the CPU and DMA runs skip the first VBLANK
and get aggregated into the next VBLANK?

[Quoted assistant reply from another session, abridged: preprocessing can
miss V1 and push the whole cold transfer to V2, delaying flip to V3; but the
first cold240 FAIL was not preprocessing delay — 240 patterns need 3,840
words against the 3,400-word single-VBlank budget, whose theoretical ceiling
is floor(3400/16) = 212 patterns.]

From this, I want to consider transferring cold patterns split across 2
VBLANKs (at 30fps). 4 VBLANKs at 15fps. Let me hear your thinking first.

## 8. A crushed face

In machi op F067D, the face of the person at upper left gets crushed and
stays that way until the scene changes, which bothers me. The face at lower
right moves, so it naturally becomes an update target and the crush resolves,
but the upper left never changes, so the Near verdict keeps the crushed look
until the scene change. I want to fix it by adjusting the cold priority logic
or something. My guess: when cold target tiles are selected at the first
appearance of this scene, they are measured by "tiles with large change,"
but because of the scene change nearly everything is near maximum change. Or
nearly tied. First, let us check why this face did not become cold. Bring
the frame info from the current data and check. (No re-sim.)

## 9. Dither edges, keep the dither

Looking at BadApple's dither expression on real hardware, the boundary areas
still bother me. Where the black-white boundary is clearly distinct, dark
dots that look like dither use stick out into the bright side, and conversely
bright dither-like dots stick out into the dark side, reading as jagged edges
and noise at the boundary. I want to fix this. But I do not want to remove
dither itself; wide gradient fills in particular look very coarsely stepped
without dither. Reconciling both may be hard, but first, without editing
files, give me ideas.

## 10. White dots that are not in the source

$new: In H40 Sonic there are frames where bright white dots appear that do
not exist in the source video. The tile category is Raw, so they do not come
from Near or Flbk. Could something be wrong in quantization?

Frame 0x012B can be confirmed in both sim and real hardware. The source has
no white dots.

In coordinates counted from the upper left, the empty area at X=05 Y=2. Other
tiles have them too.

Frame 0x0232 shows it especially prominently.

## 11. To split or not

Whether to split or not is really tricky. If it is the active period between
two VBLANKs, maybe it does not need a container? If split, things doable
during the active period become undoable. What do you think?

## 12. First report of the mystery noise

Playing on real hardware, a mysterious noise keeps sounding constantly. But
the ADPCM audio itself is audible. A real-hardware-specific PCM-RAM-not-
cleared problem seems likely first. Create a gh issue to clear PCM-RAM at
boot.

---

<a id="jp"></a>

# 開発プロンプト記録

この文書は、開発中にAIアシスタントへ送った代表的な人間のプロンプトを、
英語訳とともにverbatimで記録します。プロンプトはいずれもアシスタントへ
渡した判断・裁決・切り分け結果であり、実装手順を書いたものはありません。

日本語文が正であり、変更しません。英語文は翻訳にすぎないため、日本語を
誤訳しているときだけ直し、逆はしません。

## 1. パレットの黒の扱い

黒点に加えて輝点まで目立つようになってしまった。多候補混合は無しだ。

ただ、重要な事実を気づかせてくれた。

「全パレット行が強制的に持っている黒エントリ」

これはメガドライブのパレットの仕様からくる歪んだパレット色そのもので、今回の問題の要因とも言えそう。この黒パレットは固定なので、例外として扱うべきだ。ただ、「使わない」というのはもったいないので、パレット選定アルゴリズムが非常に深い黒を欲しがった場合は使えばいい。必要だから。SonicOPはおそらく欲しがっていないのに存在するから、2色混合で選ばれてしまうのではないか。そのパレット16色(15色)において欲しがられなかった非常に深い黒は、色再現時の道具としては「無いもの」として扱うようにしたい。

## 2. H32とmode4の切り捨て

H32は画面にたいしてドットが大きく、容量を節約できる面があることを期待していたが、ドットが大きくてディザ表現するととても荒く感じてしまい、結局どれもH40を採用してしまっている。DMA帯域も減るため、cold制限もきつくて、タイルが少なくて済んでも転送できるタイル数が少なくなってしまう。

mode4についてもBG1面とスプライトしか使えず、Windowが無い。DMAを使うにはVBLANK中にmode5との切り替えが必要になり、VBLANK超過は絶対にしてはいけなさそうで、実装難易度やビルド分岐を考えると、H40専用のCodecにしてしまおうと思う。

コードベース全体をH40専用にし、READMEにH32に対応しないことを理由を添えて軽く注記。REMOVEDにH32の削除について追記。mode4についてはどこにも書かなくていい。（書いてあるなら削除）

## 3. 実機だけで鳴る音声ノイズ

issue #81 を行ったはずですが、まだ実機メガドライブ2/メガCD2で音声にずっとノイズが乗ります。動画の再生が終わるとノイズは消えます。
アナログ系のノイズではなく音源へのデジタル系の実機だけで起きる問題です。

また、MEGA EVERDRIVE PRO から iso 起動した場合はまったくノイズが出ずクリアです。MEGA EVERDRIVE PROは内部にメガCDの回路を持っているけど実機と挙動が異なりそうですね。biosはこのメガCD2から抽出したbiosをMEGA EVERDRIVE PROで使っているので、bios差もありません。

CD-Rを何度も焼きたくないので、情報を探すなどして正確性の高い対処を行いたいです。

## 4. 自分の制約の撤回

15fpsに対応できる汎用化は絶対にやるが、ちょっと待ってください。「WordBufを先に使う」という制約を課しましたが、これは私のミスだったかもしれません。WordBufは非効率なので、あくまで「PrgBufが無くなったときに使い、PrgBufが満たされたときにrefillするスケジュールを組む」ようにすれば、「PrgBufのバックアップ」として機能して、全編fallbackしにくい気がします。また「refillを貯めなければいけないが、貯めすぎて溢れてしまうからNG」ではなく、「すぐにrefillできる配送スケジュールが組める余裕があるがあるときだけrefillする」ようにすれば、可能な範囲でrefillになります。どうですか？

## 5. 想定外の手戻りはだめ

いいと思います。後工程で制約を破ってしまい手戻りが起きるということがないパイプラインにリフレッシュしましょう。手戻り is 場当たりで対症療法です。「想定外の手戻り」はだめです。大きい仕事になりますが、利益も大きいです。そうしたクリーンなパイプラインになったあとで、「想定『内』の手戻り」としてrun数を削減する set-localiy 的な工程をまた入れましょう。

## 6. 原則の言語化

$new 先程の知見ドキュメントから普遍的に使えるものをAGENTS.md(英語)に盛り込んで。特に**「平均は合うが、期限には間に合わないschedule」の部分は重要。このプロジェクトにおいて全てのcd1x時間はすべての瞬間において一定で、平均で合わせに行くのは意味がない。これは絶対の前提。そし

## 7. 自分の考察の持ち込み

H40 Bad Apple を cold240 にしたとき、SLIPが発生して HUD gate がFAILになったあと、以下のやりとりがあった。

run fragmentationより、転送量が境界を越えて次のVBlankを待った形
30fpsだと1フレームの処理に2VBlankが使えて、最初のVBLANKと次のVBLANKがある。現在、最初のrunやCPU転送は最初のVBLANK前から行われうる？それとも前処理次第では、CPUもDMArunも最初のVBLANKでは行われず、次のVBLANKに集約されてしまったりする？
3:07
3m 33s作業しました
はい、後者は起こり得ます。まず「30fpsで2 VBlank使える」の内訳を明確にすると、現行H40 N2では通常こうです。

```
V0: 前フレームをflip
    └ active期間: swap、Pass1、shadow更新、NT staging

V1: cold pattern転送
    └ DMA runと1–2 tileのCPU直書き

V2: NT DMA、HUD、CRAM、表示flip
```

つまり、cold pattern転送に自由に使えるのは通常V1の1回です。V2は表示flip用に予約されています。
実装上の挙動

* Pass1のRUN_TABLE構築などはactive表示中に実行できます。
* 実際のVRAM pattern転送は、DMAもCPU直書きもPass2にまとめられており、VBlank内でしか実行しません。
* Pass2到達時にすでにVBlankなら、その途中から即座に転送開始します。
* active中なら、次のVBlank開始まで待ちます。
* 前処理がV1を過ぎると、cold転送全体がV2へ送られます。その後NT DMAは新しいVBlankを要求するため、flipはV3へ遅れます。


```
前処理がV1を逃した場合:

V0 ── prework ── V1(未使用) ── prework ── V2(cold) ── V3(NT DMA + flip)
```

これは現在のコードで実際に可能です。[Pass2入口 (line 989)](/home/akiyan/segacd-fmv-ttrc/boot/movieplay_ip.s:989)では、現在VBlank中ならそのまま進み、そうでなければ次を待ちます。
cold240の最初のFAILは前処理遅延ではない
`f0167` は以下でした。

* `E=0x33`、Pass2到達は前回flipから約6.27ms
* V1までは約16.7msなので、前処理は十分早い
* cold/DMA = 240 patterns
* H40の1 VBlank予算 = 3,400 words
* 240 patterns = 3,840 words

したがって、freshなV1を丸ごと使っても入りません。

```
V1: cold前半
V2: cold残り
V3: NT DMA + flip
```

これはCPU時間の推測ではなく、現在の固定word予算だけで確定します。H40で1 VBlankに入る理論上限は、

```
floor(3400 / 16) = 212 patterns
```

です。cold180は2,880 wordsなので1回に収まりますが、220、230、240はcapまで使えば必ず複数VBlankになります。
もう一つ注意点があります。Pass2がVBlankの途中に到達した場合でも、現在は残り時間を測らず、3,400 wordsの全予算を設定します。そのため、capが212付近では「VBlank途中から全予算を使おうとする」問題も別途あり得ます。ただしcold240の`f0167`はV1前に到達しているため、この問題とは無関係です。
結論として、先ほどの説明はさらに限定できます。
cold240はMain CPUが何となく重くなったのではなく、現行H40 N2プレイヤーが持つ「cold転送1 VBlank = 最大212 patterns」という固定枠を超え、表示用VBlankを消費した。
前処理によるV1取り逃しも可能ですが、最初のFAIL原因はそれではありません。


このことから、(30fpsの場合)2VBLANKに分けてcold pattern転送を行えるか考えたい。15fpsなら4VBLANKである。一度考えを聞かせて。

## 8. つぶれた顔

machi op の F067D の人物（左上）の顔がつぶれてしまってシーン切り替わりまで残ってしまい気になる。右下の顔は動いているので自然と更新対象になりつぶれが解消するが、左上は変化が無いためNear判定でそのままつぶれた感じがシーン切り替わりまで持続してしまう。cold優先度のロジックの調整か何かで解決したい。推測だが、最初にこのシーンが出る際のcold対象タイルの選定時点で「変化が大きいタイル」で測っていると思うが、シーンの切り替わりのため、全てどれも変化が最大近くになってしまっているのではないだろうか。あるいは僅差。まずはなぜこの顔のほうがcoldになっていないのか確認しよう。現行データから当該フレームの情報を持ってきて確認。（再simなどはしないで）

## 9. ディザは残す

BadAppleのディザ表現を実機で見ると、境界部分がまだ気になった。白黒境界がわかりとはっきりしているところで、明るい方に飛び出たかたちの暗いディザ用と思われるドット、また逆に暗い方に飛び出ている明るいディザ用と思われるドットが、境界のギザギザやノイズに見える。これを解決したい。ただしディザ自体は無くしたくない、特に広い範囲のグラデーション塗りなどはディザが無いと非常に階調が荒く見えてしまう。両立するのは難しいかもしれないが、まずはファイル編集せずにアイデアを出してみてほしい。

## 10. ソースに無い白点

$new H40 Sonic で元動画には無い明るい白の点が出現しているフレームがある。タイルのカテゴリはRawなのでNearやFlbk由来ではない。量子化で何かおかしなことがおきていないだろうか。

Frame 0x012B で sim、実機 ともに確認できる。ソースには白の点は存在しない。

左上から数える座標でいうと、X=05 Y=2 の空の部分。他のタイルにもある。

Frame 0x0232 なんかは特に顕著に発生して見える。

## 11. 分割の悩み

分割したほうがいいか、しないほうがいいか、とても悩ましい。2VBLANKの間にあるactive期間なら別に器にしなくてもいいんじゃない？分割したら、active期間中にできたことができない。どう思う？

## 12. 雑音の第一報

実機で再生したところ、謎の雑音が常時なりっぱなしだった。ただ、ADPCMの音声自体は聞き取れる。実機特有のPCM-RAM未クリア問題がまずは考えられる。PCM-RAMクリアをboot時に行うようにする gh issue を作成。

