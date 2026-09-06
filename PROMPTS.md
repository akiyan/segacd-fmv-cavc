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
