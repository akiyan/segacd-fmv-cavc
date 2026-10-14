# Presentation master

This file is the master for slide wording, presenter notes, timing, and visual placeholders. The Japanese section is the delivery script for the “勝手移植の世界” event; the English section is its complete translation. Update this file before changing the Canva deck. Quotations follow the authoritative Japanese text in PROMPTS.md.

- Format: 29 slides, 16:9, approximately 15 minutes including transitions.
- Audience: includes people unfamiliar with Mega Drive graphics. Introduce the motivation on slides 3–4, the hardware on slide 7, and H40, tiles, and graphics memory on slide 9.
- Current production scope: visual explanations using diagrams, the exact user-selected hardware PNG on slide 7, and the real mixline on slide 21. Preserve verbatim prompt excerpts. The opening video is played separately and has no slide placeholder. Keep geometric diagrams editable where Canva import supports native shapes.
- Layout: warm white background, dark navy text, blue and teal accents, large projection-friendly headings and numbers. Quoted text must remain verbatim; line breaks may change.
- Visual references: hardware diagram titled “MD MCD のリソースと配線”; mixline reference is the Sonic Jam OP e171/p144 result at https://gist.github.com/akiyan/f81d473dbde22a7a5699efcb03ca302d. Keep the complete diagnostic header and status visible when this image is eventually inserted. The header reflects that recording’s historical validation rules, not a new qualification.
- Timing is a rehearsal target, not a measured speaking duration.
- Canva design: [Open the 29-slide visual edition](https://www.canva.com/d/0qQtIibKCP05hQ0) (design ID: `DAHVx2QwKdI`). The generated HTML is at `tmp/presentation/presentation.html`.

## 01. Full-screen 30 fps video on Mega-CD

Time: 0:00–0:25

### On-slide text

Full-screen 30 fps video on Mega-CD

Tile-pattern reuse and resources dedicated to video playback

### Visual placeholder

None. The presenter switches to the playback video separately.

### Speaker notes

I built a codec that plays full-screen video at 30 fps on Mega-CD. It can run on real hardware from a burned CD-R. I will switch to the playback video separately, then explain how it works and how I developed it with Claude and Codex.

## 02. Codec specifications

Time: 0:25–1:05

### On-slide text

- 30 / 24 / 15 fps
- Up to 320 × 224 pixels
- Four palettes, up to 60 colors
- Dynamic palette switching during playback
- Palette fades for fade-ins and fade-outs, including dark transitions
- Hardware scrolling for pans and tilts

### Visual placeholder

Use six compact illustrated specification cards: a frame-rate timeline, 320 × 224 screen, four palette strips totaling 60 usable colors, palette replacement during playback, a brightness ramp for palette fades, and pan/tilt arrows over a larger virtual image for hardware scrolling.

### Speaker notes

First, these are the codec's playback specifications. It supports source cadences of 30, 24, and 15 fps, with a maximum 320 by 224 frame. It can use four palettes for up to 60 visible colors, switch palettes dynamically during playback, turn fades into palette fades, and use the Mega Drive's hardware scrolling for pans and tilts. Later slides explain the hardware and encoder work behind these features.

### Production notes

The four palettes provide fifteen independently chosen visible colors each because the transparent entry is shared, for a maximum of sixty visible colors.

## 03. Why I made this: it began with Machi

Time: 1:05–1:45

### On-slide text

- Burned out on Kamaitachi no Yoru MD
- Started a Mega-CD port of Machi
- Its opening movie required a video player
- Machi opening: 320 × 144 / 15 fps / black bars
- What would full-screen 320 × 224 / 30 fps look like?

### Visual placeholder

A left-to-right origin story: “Kamaitachi no Yoru MD” fatigue leads to “Machi Mega-CD port,” then to the need for an opening-movie player. Compare the original 320 × 144, 15 fps image inside black bars with a full-screen 320 × 224, 30 fps target.

### Speaker notes

When I got tired of working on Kamaitachi no Yoru MD, I began a Mega-CD port of Machi. Machi has an opening movie, so the port needed a way to play it. The original movie uses a 320 by 144 image with black bars at 15 fps. That made me wonder how far the hardware could go: what quality could I get from a full-screen 320 by 224 movie at 30 fps? That question became the start of this codec.

## 04. Why Mega-CD was worth the challenge

Time: 1:45–2:07

### On-slide text

Large storage, narrow delivery path.

CD 1×: about 150 KiB/s

Full-color footage with up to 60 colors

### Visual placeholder

Generated illustration of a large CD delivering through a narrow pipe to a colorful display. Preserve the existing Bad Apple thumbnail, uploader and URL in a comparison panel.

### Speaker notes

A full-screen 30 fps Mega Drive Bad Apple already existed, but I did not know of a Mega-CD version. Mega-CD has more storage but only about 150 KiB/s at CD 1×. Reading while presenting video and audio was a worthwhile challenge. I wanted full-color footage with up to 60 colors.

## 05. Why I hurried to combine every idea

Time: 2:07–2:30

### On-slide text

Tile reuse / palette switching / palette fades / hardware scrolling

In the AI era, someone would attempt it.

Near completion, Virtua Fighter and Ridge Racer ports and other MD FMV projects gained attention.

### Visual placeholder

Four feature cards above a timeline: AI era → hurry → unofficial ports gaining attention near completion.

### Speaker notes

I wanted to combine tile reuse, palette changes, palette fades and hardware scrolling. As far as I know, that combination of fades and scrolling is unique outside animation-style players. I hurried because someone seemed likely to attempt this in the AI era. Near completion, Virtua Fighter and Ridge Racer ports gained attention, and I saw other Mega Drive FMV projects.

## 06. Fifty days of development with AI

Time: 2:30–3:05

### On-slide text

- 50 days, with work on 42 days
- Around 6 hours of hands-on work per working day
- Claude and Codex, both on $100/month 5x plans at the time
- Both weekly usage limits consistently exhausted
- All accumulated Codex reset credits used as well

### Visual placeholder

None. Typography and large numbers only.

### Speaker notes

I used Claude and Codex for development. I worked on 42 of the 50 days, around six hours a day. I consistently exhausted both weekly limits and also used all the Codex reset credits I had accumulated. AI handled implementation, encoding, emulator recording, and log analysis. Even with AI, it was a huge amount of work. I will show what that work looked like later.

### Production notes

Duration, working hours, plans, and usage are the presenter’s account of the development period. Do not replace them with earlier draft estimates or current subscription details.

## 07. MD MCD resources and wiring

Time: 3:05–4:20

### On-slide text

MD MCD のリソースと配線

### Visual placeholder

Insert the exact user-selected PNG `exec-01e3c5c9-e042-48cb-b525-fd1dc516d466.png`, titled “MD MCD のリソースと配線”, as a complete slide without cropping. Source: `/home/akiyan/.codex/generated_images/01a089e0-559f-71c2-aa2a-7d7a6747121f/exec-01e3c5c9-e042-48cb-b525-fd1dc516d466.png`. Left: Mega Drive. Center: gate array and WORD-RAM. Right: Mega-CD. Preserve its CPU clocks, memory capacities, bus labels, omitted CRAM/VSRAM, teal PCM output, and CPU-write/DMA label.

### Speaker notes

Mega Drive is on the left and Mega-CD on the right. The left has the 7.67 MHz Main CPU, 64 KB MAIN-RAM, the VDP, and 64 KB VRAM. Both CPU writes and DMA reach VRAM through the VDP. For DMA, the CPU sets the transfer conditions and the VDP reads data from memory in a block. The right has a 12.5 MHz Sub CPU and 512 KB PRG-RAM. It reads the CD and decodes compressed audio, which plays through the Mega-CD PCM chip. The central WORD-RAM totals 256 KB. We use two 128 KB banks, with Main and Sub owning different banks and exchanging them. I also tried audio processing on the Z80, but feeding it contended with the Main bus and interfered with video processing, so I did not use it in the final player. A bus is the route that carries data. Spare CPU or memory is only useful when that route can support the work too.

## 08. Resource pipeline overview

Time: 4:20–4:50

### On-slide text

- Sub CPU: CD reads, next-frame preparation, audio decoding
- Main CPU + VDP: pattern transfers and display updates
- WORD-RAM: next-frame handoff

### Visual placeholder

A numbered board-game-style continuous route: 1 CD, 2 read and prefetch into PRG-RAM, 3 Sub prepares the next frame, 4 handoff through two Word-RAM banks, 5 Main sets the VDP, 6 VDP transfers to VRAM, 7 video output. Travel right along the top, turn down at Word RAM, then travel left. Background colors distinguish Mega-CD from Mega Drive. Show two 128 KiB banks: Sub builds one while Main reads the other, then ownership swaps for the next frame. Audio branches from step 2 through Sub decoding, PCM RAM and the PCM chip.

### Speaker notes

The Sub CPU reads the CD and prepares the next frame while storing future patterns. Main sends the received data to the VDP and updates the display. There is no need to reserve resources for game logic or map management. That capacity goes into prefetching, retaining patterns, and playing video and audio.

## 09. The adopted H40 screen mode

Time: 4:50–5:12

### On-slide text

H40: 40 × 28 tiles
320 × 224 pixels / 1,120 positions

One tile: 8 × 8 pixels, 32 bytes
One screen: 35 KiB of patterns, about 55% of 64 KiB VRAM

H32 and mode4 were tried and removed because the result was unsatisfactory.

### Visual placeholder

Exact 40 × 28 grid, enlarged 8 × 8 tile and 64 KiB VRAM capacity diagram. Transfer bandwidth is explained on the next page.

### Speaker notes

H40 specifies 40 tiles across. With 28 NTSC rows, it gives 320 × 224 pixels and 1,120 positions. Each 8 × 8 tile takes 32 bytes. Distinct patterns for all positions take 35 KiB, about 55% of 64 KiB VRAM. I also implemented and tried H32 and mode4, then removed them because the result was unsatisfactory.

## 10. Sending every pattern every frame needs seven times CD bandwidth

Time: 5:12–5:35

### On-slide text

35 KiB per screen × 30 fps
= 1,050 KiB/s

CD 1×: 150 KiB/s

Resending everything cannot fit. Reuse is necessary.

### Visual placeholder

Compare one CD-bandwidth unit with seven required units at the same scale, with large figures.

### Speaker notes

Resending 35 KiB of patterns 30 times a second requires 1,050 KiB/s, seven times the CD 1× rate of 150 KiB/s, even before audio or control data. This is why pattern reuse and prefetching are necessary.

## 11. Thirty fps must fit into two VBlank intervals

Time: 5:35–6:20

### On-slide text

VBlank: the short interval when the visible picture is not being drawn

Display interval spanning 2 VBlanks: approximately 33 ms

Display interval spanning 3 VBlanks: approximately 50 ms

### Visual placeholder

Two time tracks compare a 33 ms frame held for two NTSC refresh periods with a delayed 50 ms frame held for three. Vertical green bands mark VBlank. Band widths are schematic, not measured blanking durations.

### Speaker notes

VRAM transfers have a timing constraint too. VBlank is the short interval when the visible picture is not being drawn. This player fits display-update transfers into that interval. Writes during active display are possible, but bandwidth falls sharply and partially updated images can become visible. NTSC has around 60 VBlanks per second, so 30 fps needs a new frame every two. Taking three holds that frame for around 50 milliseconds and causes a visible jerk. If delays accumulate, prefetched data can fill its available space. Servicing the continuous CD read can then stall and playback can break down.

## 12. The bytes may fit while the work does not

Time: 6:20–7:00

### On-slide text

- DMA setup and completion waits take time
- Many small transfers accumulate overhead
- Starting partway through VBlank leaves less time

How much data, when it starts, and how many transfers

### Visual placeholder

Two horizontal bars carry the same amount of payload. Orange setup segments repeat in the fragmented transfer, pushing it past the VBlank deadline. This is a conceptual cost comparison, not measured timings.

### Speaker notes

This took considerable work. Large DMAs initially ran beyond VBlank, so I split them into pieces that fit. But smaller pieces are not automatically better: every transfer needs setup and completion handling. I moved setup calculations into active display time and transferred the name table in a single DMA. Some reordered processing experiments made waiting worse. Byte totals did not explain everything, so I measured which scanline preparation finished on and which transfers happened in each VBlank.

### Production notes

Evidence: f811522 (July 8, split DMA to fit VBlank); 7e80d4f and 56adaa2 (July 22, prepare DMA settings earlier and DMA the name table); 28f1788 and 9708d3f (July 28, split at VBlank boundaries and account for CPU-write cost); cdc4ca1 (July 30, measure DMA started partway through VBlank). See harness/cold_cap_model/README.md for experiments and rejected explanations. Do not present the subsequently rejected normal-frame phase-ratchet hypothesis as the established cause.

## 13. Now, the encoder

Time: 7:00–7:25

### On-slide text

Player optimization mattered.

Encoder optimization mattered even more.

On the PC: decide what to send, when, and where

### Visual placeholder

None. Section-transition slide with large typography.

### Speaker notes

So far I have described the player running on Mega-CD. Now I will describe the encoder that creates playback data on a PC. Player optimization was important, but encoder optimization was even more important. A faster player still cannot meet the deadline if it receives work that cannot fit into two VBlanks. The amount and shape of that work must be prepared before playback.

## 14. Tile-pattern reuse

Time: 7:25–7:55

### On-slide text

| Picture state | Encoder decision |
|---|---|
| Already good enough | Keep the current display |
| A usable pattern exists in VRAM | Reuse it |
| A similar pattern is sufficient | Use the close match |
| A new pattern is needed | Allocate a transfer |

### Visual placeholder

Four-row decision diagram. The first three rows show keeping or reusing a pattern. In the final row, a “32 B transfer data” block flows into a newly loaded VRAM pattern, rather than showing the same tile on both sides.

### Speaker notes

The encoder examines each frame and chooses where new patterns are needed. It reuses identical patterns and uses close matches where they are sufficient. It sends new patterns where spending the transfer budget is worthwhile. Those choices determine the visible quality.

## 15. Prefetch schedules are also decided during encoding

Time: 7:55–8:25

### On-slide text

Fill all buffers before the first frame plays.

Decide refill data ahead of time and fit it into CD 1x bandwidth when playback has spare capacity.

Planning during encoding makes it possible to buffer patterns needed far into the future.

### Visual placeholder

Three generously spaced text statements, with a small schematic below: fill before playback → refill during spare capacity → use in a far-future frame.

### Speaker notes

The encoder decides the prefetch schedule for the whole movie. Before playback begins, fill each buffer's allocated preload region to its planned startup amount. Refill data is selected ahead of time and placed on the CD 1x stream for less demanding playback intervals. Knowing future frames allows patterns to be buffered well before they are needed.

## 16. Calculate ahead: ADPCM audio

Time: 8:25–8:40

### On-slide text

The final missing resource was CPU time

PCM hardware cannot play ADPCM directly

Repeated arithmetic → prepared table lookups
Lookup tables in Sub PRG-RAM → PCM samples

### Visual placeholder

Concrete ADPCM decoder flow: 4-bit code and step index select precomputed delta and next-index tables in Sub PRG-RAM; Sub adds and clamps the predictor; the output table converts it for PCM RAM and the PCM chip. Arithmetic is reduced, not eliminated.

### Speaker notes

Sub still performs addition, range limiting, and writes to PCM RAM after lookup. The last missing resource for stable playback was CPU time. The Mega-CD PCM chip cannot play ADPCM directly. Full lookup tables in Sub PRG-RAM replace repeated decoding arithmetic with table lookups and reduce real-time CPU work.

## 17. Store tile artwork separately from its placement

Time: 8:40–9:10

### On-slide text

Pattern table: numbered tile artwork. Each pattern is 8×8 pixels.

Name table: each screen cell records which pattern number to use. The same number can be used repeatedly.

Both are stored in VRAM. The VDP reads the numbers and arranges the artwork on screen.

To update video, transfer the required patterns and placement table to VRAM. DMA performs these transfers in blocks.

### Visual placeholder

Use the approved preview without changes: grass, sky and cloud patterns numbered 1–3; a 4×3 name table; the matching rendered scene. The actual H40 screen has 40×28 cells. Approved image: /dev/shm/segacd-fmv-cavc/presentation/proposals/tables-preview.png.

### Speaker notes

A pattern table stores the artwork for 8×8-pixel tiles. A name table stores which tile appears at each screen position. Several positions can refer to the same pattern, so repeating an image does not require another copy of its artwork. Both are stored in VRAM and the VDP combines them to draw the screen. Entries also specify palette and flip attributes; the diagram omits these to focus on the relationship between artwork and placement. The next slide explains precomputed DMA settings used to transfer this data.

## 18. Scattered pattern locations increase DMA count

Time: approximately 30 seconds

### On-slide text

The same four patterns, but different destination locations in VRAM.

Contiguous placement: one DMA. Scattered placement: four DMAs.

The same 128 bytes require more setup, starts, and completion waits.

Fitting into VBlank requires controlling both byte volume and DMA count.

### Visual placeholder

Use the approved comparison preview unchanged: /dev/shm/segacd-fmv-cavc/presentation/proposals/fragmentation-preview.png. Contiguous RAM source patterns A–D go to VRAM slots 40–43 on the left or 40, 42, 44, 46 on the right. Gray cells hold retained patterns. One pattern is 32 bytes; VBlank splitting and post-transfer correction are omitted.

### Speaker notes

Patterns retained for reuse occupy some VRAM slots. If available destinations are scattered among them, four new patterns cannot be transferred as one contiguous run without overwriting retained data. The diagram compares one run with four runs for the same 128 bytes, assuming contiguous source data and no VBlank-boundary split. More runs mean more transfer setup and completion handling. The encoder therefore needs to consider placement and transfer runs as well as total bytes. Next, explain precomputing the DMA settings.

## 19. Calculate ahead: DMA addresses

Time: 8:40–8:55

### On-slide text

PC precomputes source RAM and destination VRAM addresses

Results are stored in the stream

The console reads values and configures the VDP

A codec specifically for Mega Drive + Mega-CD

### Visual placeholder

Three concrete stages: the PC decides RAM sources and VRAM destinations and creates VDP settings; the stream stores source, destination and length settings; Main reads and writes those settings to the VDP for VBlank DMA. Show the separate pattern-data route from Word/Main RAM through the VDP to VRAM.

### Speaker notes

DMA needs a RAM source address and a VRAM destination address. The encoder calculates them ahead and stores the results in the stream. The player reads those values and configures the VDP. Preparing the work on the PC saves real-time CPU time: this codec is specifically for Mega Drive and Mega-CD.

## 20. Human work: finding structures to optimize

Time: 9:25–9:50

### On-slide text

Finding structures to optimize

### Visual placeholder

A loop connects thinking about the structure, implementing with AI, and measuring. Center this loop without the three-column summary above it. The approved short speaker script stays unchanged.

### Speaker notes

The other task was finding structures to optimize. Where can data remain to reduce transfers? Which work can be completed earlier? Could a different order make better use of memory? I explored those structures through repeated implementation and measurement with AI.

### Production notes

Keep this section to the agreed short script. Do not include the withdrawn-constraint quotation or discussion of personal mistakes.

## 21. Timeline of encoder results and measured playback logs

Time: 9:50–10:10

### On-slide text

Timeline of encoder results and measured playback logs

### Visual placeholder

Show only the title and the complete existing Sonic Jam OP e171/p144 mixline image, preserving its original header and recorded status. Remove every other on-slide label, arrow, kicker, footer, and page number. Source for the presenter notes: https://gist.github.com/akiyan/f81d473dbde22a7a5699efcb03ca302d. This is historical evidence, not a fresh qualification.

### Speaker notes

I checked optimization results with an image called mixline. The top shows encoder decisions and the bottom shows measurements from emulator playback, aligned on the same frame axis. The next slide lists every indicator.

## 22. All mixline indicators

Time: 10:10–10:30

### On-slide text

Encoder: REQ, SUPPLY, RUN, R2V, DIC, BAND

Player: VBLANK, PATTERN READY PRESSURE, NT READY PRESSURE, SECTOR SLIP, CONTROL DESYNC, AUDIO RESYNC, VBLANK SPILL, PRGBUF JITTER, SUB PUMP GAP, MSF GAP, APPLY BACKPRESSURE, READER AHEAD, READER SLOT, TRANSFER VBLANKS, TRANSFER END, CD WAIT, AUDIO LEAD, SUB HANDOFF, ADPCM, PATTERN TRANSFER, COLD RUNS, FLIP VCOUNTER, FIRST SHARE EXIT, PASS2 DELAY

### Visual placeholder

Three-column table containing all 30 rows from the exact timeline and hudline layout receipts used by the displayed mixline. Give every indicator a one-line plain-language explanation. Smaller text is allowed.

### Speaker notes

The mixline combines six encoder indicators and twenty-four playback indicators. The table gives each row a short reading guide. REQ also contains the decision classes Raw, Same, Near, Flbk, Miss, Prg, Wrd, and Dic. These names and units come from the machine-readable layout receipts for the displayed mixline, not from visual interpretation.

### Production notes

Source definitions: the matching timeline-layout and hudline-layout JSON receipts under logs for Sonic Jam OP e171/p144.

## 23. Four especially useful indicators

Time: 10:35–11:00

### On-slide text

VBLANK — Display cadence
Check whether a 30 fps frame stays within two VBlanks. Locate cadence overruns.

R2V — Transfer volume
Compare planned words sent to the VDP with playback delays. Separate too many bytes from preparation and transfer overhead.

PRGBUF JITTER — Buffer headroom
Measure peak use of the reserved jitter margin. Decide how much physical PRG-RAM must remain outside the encoder's normal budget.

ADPCM — Audio CPU time
Measure Sub-CPU decoding time. Check whether audio work leaves time for CD service and frame preparation.

### Visual placeholder

Four clean rows, each with the indicator name, what it measures, and the decision it supports. No decorative images.

### Speaker notes

VBLANK locates frames that miss the intended display cadence. R2V shows planned transfer volume, so comparing it with live timing helps distinguish volume from CPU preparation and per-transfer overhead. PRGBUF JITTER is a retained peak of runtime margin use, not current buffer occupancy; it informs the gap between the physical ring and the encoder budget. ADPCM measures decoding time on Sub, helping evaluate the audio workload alongside CD pumping and frame handoff. Read these on the same frame axis rather than treating one value alone as proof of the cause.

## 24. Prompt example: a VBlank hypothesis

Time: 10:30–11:10

### On-slide text

> When H40 Bad Apple at cold240 produced SLIP and the HUD gate FAILED, the following exchange happened.
>
> More like transfer volume crossing the boundary and waiting for the next VBlank than run fragmentation. At 30fps one frame can use 2 VBlanks, the first VBLANK and the next VBLANK. Can the first runs and CPU transfers run before the first VBLANK now? Or, depending on preprocessing, could the CPU and DMA runs skip the first VBLANK and get aggregated into the next VBLANK?

Source: PROMPTS.md, section 7.

### Visual placeholder

Place the verbatim quotation inside a simplified generic prompt input form with generous line spacing. On the right, show two VBlank windows and the question of whether preparation misses the first one and piles transfers into the second.

### Speaker notes

I also brought my own hypotheses into the discussion. Here I asked whether preparation timing, rather than only transfer fragmentation, caused work to miss the first of the two VBlank opportunities available at 30 fps.

## 25. Prompt example: treating palette black as an exception

Time: 11:10–11:50

### On-slide text

> In addition to dark specks, bright specks have now become noticeable. Drop the multi-candidate mixing.
>
> But it made me notice one important fact.
>
> "The black entry that every palette line forcibly carries."
>
> This is itself a distorted palette colour coming from the Mega Drive palette specification, and it looks like a cause of the current problem. This black palette is fixed, so it should be treated as an exception. But leaving it unused would be a waste, so the palette selection algorithm may use it when it genuinely wants a very deep black. Because it needs it. SonicOP probably is not asking for it, yet it exists, so it may be getting picked through two-colour mixing. A very deep black that was not wanted in that 16-colour (15-colour) palette should be treated as nonexistent as a colour-reproduction tool.

Source: PROMPTS.md, section 1.

### Visual placeholder

Place the verbatim quotation inside the same generic prompt form. On the right, show four 16-entry palette rows with their forced black entry isolated, then an arrow showing that black is used only when the segment actually needs a deep black.

### Speaker notes

The Mega Drive forces a black entry into every palette row. I identified that the encoder could accidentally treat this fixed entry as an ordinary mixing color even when the scene did not ask for deep black. The prompt states both the exception and the condition under which the color should remain available.

## 26. Prompt example: tracing a crushed face

Time: 11:50–12:30

### On-slide text

> In machi op F067D, the face of the person at upper left gets crushed and stays that way until the scene changes, which bothers me. The face at lower right moves, so it naturally becomes an update target and the crush resolves, but the upper left never changes, so the Near verdict keeps the crushed look until the scene change. I want to fix it by adjusting the cold priority logic or something. My guess: when cold target tiles are selected at the first appearance of this scene, they are measured by "tiles with large change," but because of the scene change nearly everything is near maximum change. Or nearly tied. First, let us check why this face did not become cold. Bring the frame info from the current data and check. (No re-sim.)

Source: PROMPTS.md, section 8.

### Visual placeholder

Place the verbatim quotation inside the same generic prompt form. On the right, use a three-step schematic: the face is distorted, the subject stays still, and the Near result keeps the distortion until the scene changes.

### Speaker notes

This prompt starts with a specific frame and visual problem, compares two faces whose motion differs, offers a hypothesis about cold priority at a scene cut, and asks to inspect existing data without running another simulation.

## 27. Prompt example: choosing H40

Time: 12:30–13:10

### On-slide text

> H32 has larger dots relative to the screen, and I had hoped that would save capacity, but the larger dots make dithered expression feel very coarse, so in the end everything adopted H40. The DMA bandwidth also shrinks, tightening the cold limit: even though fewer tiles are needed, fewer tiles can be transferred.
>
> Mode4 also offers only one BG plane plus sprites, with no Window. Using DMA would require switching between mode4 and mode5 inside VBlank, and exceeding VBlank must never happen, so considering implementation difficulty and build branching, I will make this an H40-only codec.

Source: PROMPTS.md, section 2, excerpt.

### Visual placeholder

Place the verbatim quotation inside the same generic prompt form. On the right, compare H32 and H40 as tile grids and show that H32 has larger dots but less DMA bandwidth.

### Speaker notes

This prompt made a product-level scope decision from both visual quality and hardware limits. H32 uses fewer, larger dots, but dither looks coarser and the VDP can transfer fewer tiles. I asked to make the codec H40-only after weighing the tradeoff.

## 28. Prompt example: noise only on real hardware

Time: 13:10–14:25

### On-slide text

> This is not analog noise; it is a digital sound-source problem that occurs only on real hardware.
>
> Booting the ISO from MEGA EVERDRIVE PRO produces completely clear audio without noise. MEGA EVERDRIVE PRO has Mega-CD circuitry inside, but its behavior seems to differ from real hardware. It uses the BIOS extracted from this same Mega-CD 2, so there is no BIOS difference either.
>
> I do not want to keep burning CD-Rs, so I want a well-supported remedy based on research.

Source: PROMPTS.md, section 3, excerpt.

### Visual placeholder

Place the complete verbatim Japanese excerpt inside the same generic prompt form. A comparison on the right shows the same BIOS with noise on real Mega-CD and clear audio on MEGA EVERDRIVE PRO. These are schematic labels, not device photographs or measured waveforms.

### Speaker notes

This was the final real-hardware audio investigation. Noise occurred on a real Mega-CD but not on MEGA EVERDRIVE PRO, which provides Mega-CD functionality. Both used the same BIOS. I included the comparison conditions and what was already known. The final sentence about not wanting to keep burning CD-Rs expresses exactly how I felt. The work involved observing behavior, isolating conditions, and discussing what to investigate next, as well as having AI write code.

## 29. Thank you

Time: 14:25–15:00

### On-slide text

Thank you!

### Visual placeholder

None. Display only the thank-you message at large size.

### Speaker notes

Thank you.

---

# プレゼン原稿マスター

このファイルを、スライド文言・発表原稿・時間配分・画像のアテのマスターとする。日本語版は「勝手移植の世界」での発表用原稿、英語版はその全文訳。Canvaを修正する前にこの原稿を更新する。プロンプトの引用はPROMPTS.mdの日本語原文を正とする。

- 形式：全29枚、16:9、切り替えを含め約15分。
- 聴衆：メガドライブの画面の仕組みを知らない人も含む。3〜4枚目で制作動機、7枚目でハードウェア、9枚目でH40、タイル、画像用メモリの基本を説明する。
- 今回の制作範囲：説明用の図を中心に再レイアウト。7枚目は指定の配線PNG、21枚目は実際のmixlineを使用。プロンプト引用は原文を維持。冒頭映像は別画面で再生し、スライド上にアテを置かない。格子や時間軸はCanvaが対応する範囲で編集可能な図形として取り込む。
- レイアウト：白に近い背景、濃紺の文字、青と緑のアクセント。プロジェクターで読みやすい大きな見出しと数字。引用原文は変更せず、改行のみ調整可能。
- 画像参照：ハードウェア図「MD MCD のリソースと配線」。mixlineはSonic Jam OP e171/p144の https://gist.github.com/akiyan/f81d473dbde22a7a5699efcb03ca302d を使用予定。挿入時は診断ヘッダーと判定を残す。判定は当該記録時点の検証ルールによるもので、新たな検証結果として扱わない。
- 時間配分はリハーサル用の目安で、実際に読み上げた計測値ではない。
- Canva資料：[29枚の図解版を開く](https://www.canva.com/d/0qQtIibKCP05hQ0)（デザインID：`DAHVx2QwKdI`）。生成済みHTMLは `tmp/presentation/presentation.html`。

## 01. メガCDでフルスクリーン30fps動画を流す

時間：0:00–0:25

### スライド文言

メガCDでフルスクリーン30fps動画を流す

タイルパターンの再利用と、動画専用の資源配分

### 画像のアテ

なし。再生映像は発表者が別画面へ切り替えて流す。

### 話すこと

メガCDで、フルスクリーン30fpsの動画を流すコーデックを作りました。焼いたCD-Rを実機に入れて再生できます。ここで別画面の映像へ切り替えて再生します。その後、仕組みとClaude・Codexを使って開発した話をします。

## 02. このCodecのスペック

時間：0:25–1:05

### スライド文言

- 30fps／24fps／15fps対応
- 最大320×224対応
- 4パレット・最大60色再生
- 再生中のダイナミックなパレット切り替え
- 暗転時などのフェードイン・アウトをパレットフェード化
- パンとチルト時にハードウェアスクロールを利用

### 画像のアテ

6つの小さな仕様図を並べる。フレームレートの時間軸、320×224画面、合計60色の4本のパレット、再生中のパレット交換、明暗のパレットフェード、大きな仮想画像上を移動するパン・チルト矢印を示す。

### 話すこと

まず、このCodecで再生できる映像の仕様です。30fps、24fps、15fpsに対応し、最大320×224ドット。4本のパレットで最大60色を使えます。再生中にパレットを切り替え、暗転などのフェードイン・アウトはパレットの色を段階的に変えて表現します。パンとチルトでは、メガドライブのハードウェアスクロールも利用します。この後、そのために使ったハードウェアとエンコーダー側の工夫を説明します。

### 制作メモ

4本のパレットは、それぞれ透明色と共有する1色を除く15色を独立して選べるため、画面上では最大60色を使う。

## 03. なぜこれを作ったか：街から始まった

時間：1:05–1:45

### スライド文言

- 「かまいたちの夜MD」の作業に疲れた
- 「街」のメガCD移植を開始
- オープニングムービーへの対応が必要
- 街OP：320×144・15fps・黒帯
- 320×224・30fpsの全画面なら、どこまで高画質にできる？

### 画像のアテ

左から右へ、「かまいたちの夜MDで疲れる」→「街のメガCD移植」→「OP動画プレイヤーが必要」という発端をつなぐ。後半は、黒帯の中に320×144・15fpsを置いた元映像と、320×224・30fpsの全画面目標を比較する。

### 話すこと

「かまいたちの夜MD」の作業に疲れたとき、「街」のメガCD移植を始めました。「街」にはオープニングムービーがあるので、その再生に対応する必要がありました。元のオープニングムービーは、黒帯の中に320×144ドットの映像を15fpsで表示しています。そこで、メガCDで320×224ドットの全画面を30fpsにしたら、どこまで高画質にできるのか見てみたくなりました。この疑問が、このCodecの出発点です。

## 04. なぜこれを作ったか：メガCDで挑む理由

時間：1:45–2:07

### スライド文言

容量は大きい。でも、通り道は細い。

CD 1倍速：約150 KiB/s

フルカラー動画を最大60色で再生したい

### 画像のアテ

大容量のCDから細い管を通してカラー画面へ送る生成イラスト。Bad Appleの既存引用画像、投稿者名、URLを左の比較枠に残す。

### 話すこと

メガドライブ版の全画面30fps「Bad Apple」は既に存在しましたが、メガCD版は知りませんでした。メガCDは容量面では有利でも、CD 1倍速の帯域は約150KiB/s。読み込みながら映像と音声を出す難しさに挑戦する価値があると思いました。白黒ではなく、フルカラーの動画を最大60色で見てみたかったのです。

## 05. なぜこれを作ったか：全部盛りを急いだ理由

時間：2:07–2:30

### スライド文言

タイル再利用／パレット切替／パレットフェード／HWスクロール

AI時代、きっと誰かがやる。

完成間近に、VF・リッジレーサーの勝手移植や他のMD系FMVが話題に

### 画像のアテ

4つの機能カードを上段に置き、下段に「AI時代→急ぐ→完成間近のportの広がり」の時間軸を置く。

### 話すこと

タイル再利用、動画の途中でのパレット切替、パレットフェード、ハードウェアスクロールを全部盛り込んでみたかった。知る限り、アニメーション系のプレイヤー以外でパレットフェードとHWスクロールを組み合わせる動画Codecは唯一です。AI時代なら誰かがやりそうなので急ぎました。完成間近にはバーチャファイターやリッジレーサーの勝手移植が話題になり、ほかのメガドラ系FMVも見かけました。

## 06. AIと作った50日間

時間：2:30–3:05

### スライド文言

- 50日間で稼働42日
- 実働は毎日6時間前後
- Claude・Codex、当時ともに月100ドルの5xプラン
- 両方とも毎週の利用上限まで使用
- Codexは、たまっていたリセット権もすべて使用

### 画像のアテ

なし。文字と大きな数字のみ。

### 話すこと

開発にはClaudeとCodexを使いました。50日間のうち42日作業して、実働は毎日6時間前後です。ClaudeもCodexも常に週間上限を使い切り、Codexはたまっていたリセット権もすべて使い切りました。実装だけでなく、エンコード、エミュレータ録画、ログ解析までAIに進めてもらいました。AIを使いましたが、めちゃくちゃ大変でした。その中身も後半で話します。

### 制作メモ

期間・稼働時間・プラン・利用量は開発当時の本人申告。過去の下書きの概算値や、現在のサービス仕様に置き換えない。

## 07. MD MCD のリソースと配線

時間：3:05–4:20

### スライド文言

MD MCD のリソースと配線

### 画像のアテ

ユーザー指定の既存PNG `exec-01e3c5c9-e042-48cb-b525-fd1dc516d466.png`（タイトル「MD MCD のリソースと配線」）を、切り抜かず1枚のスライド全面に挿入する。元ファイル：`/home/akiyan/.codex/generated_images/01a089e0-559f-71c2-aa2a-7d7a6747121f/exec-01e3c5c9-e042-48cb-b525-fd1dc516d466.png`。左：メガドライブ、中央：ゲートアレイとWORD-RAM、右：メガCD。CPUクロック・メモリ容量・バス表記、CRAM/VSRAM省略、PCM出力の緑、CPU書き込み/DMAの表示をそのまま使用する。

### 話すこと

左がメガドライブ、右がメガCDです。左には7.67MHzのメインCPU、64KBのMAIN-RAM、画面を作るVDP、64KBのVRAMがあります。CPUからの書き込みもDMA転送も、VDPを通ってVRAMへ入ります。DMAは、CPUが転送条件を設定すると、VDPがメモリからまとめて読み出す仕組みです。右には12.5MHzのサブCPUと512KBのPRG-RAMがあります。CDの読み込みと、圧縮音声の展開を担当します。音はメガCD側のPCM音源から出します。中央のWORD-RAMは合計256KB。今回は128KBずつに分け、MainとSubが別々のバンクを使い、交換してデータを受け渡します。左下のZ80にも音声処理を任せようとしました。ただ、データを補給する際にMain側のバスと競合し、映像処理に影響するため不採用にしました。バスはデータの通り道です。メモリやCPUが空いていても、そこへ運ぶ道まで含めて考える必要があります。

## 08. リソースパイプラインの概要

時間：4:20–4:50

### スライド文言

- Sub CPU：CD読み込み・次のコマの準備・音声の展開
- Main CPU＋VDP：パターン転送・表示更新
- WORD-RAM：次のコマを受け渡す

### 画像のアテ

すごろく型の番号付き一本道。①CD→②PRG-RAMへ読み込み・先読み→③Subが次コマ準備→④WORD-RAMの2バンクで受け渡し→⑤MainがVDP設定→⑥VDP経由でVRAM転送→⑦映像出力。上段を右へ進み、WORD-RAMで下段へ折り返して左へ進む。背景色でメガCD側からメガドライブ側への切り替わりを示す。WORD-RAMは128 KiB×2で、一方をSubが作成中に他方をMainが読み、次コマで所有権を交換する。音声は②からSub展開→PCM RAM→PCM音源へ分岐。

### 話すこと

サブCPUがCDを読み、将来使うパターンをためながら、次のコマを準備します。メインCPUは受け取ったデータをVDPへ送り、画面を更新します。ゲームロジックやマップ管理に資源を残す必要はありません。その分を、先読み、パターンの保持、映像と音声の再生に使いました。

## 09. 採用した画面モードH40とは

時間：4:50–5:12

### スライド文言

H40＝横40タイル × 縦28タイル
320×224ドット／1,120マス

1タイル＝8×8ドット・32バイト
画面1枚のパターン＝35 KiB／VRAM 64 KiBの約55%

H32とmode4も試したが微妙だったので対応自体を削除

### 画像のアテ

寸法が正確な40×28格子、8×8タイル拡大、64KiBのVRAM容量図。転送帯域の計算は次のページへ。

### 話すこと

H40は横40タイルの画面モードです。NTSCの縦28タイルで320×224ドット、1,120マスになります。1タイルは8×8ドットで32バイト。すべて別々の絵柄にすると、画面1枚のパターンだけで35KiB、64KiBのVRAMの約55%です。H32とmode4も実装して試しましたが微妙だったので対応自体を削除しました。

## 10. 全画面を毎コマ送ると、CD帯域の7倍

時間：5:12–5:35

### スライド文言

画面1枚 35 KiB × 30fps
＝1,050 KiB/s

CD 1倍速：150 KiB/s

全部送り直す方法では足りない。再利用が必要。

### 画像のアテ

同じ縮尺でCD帯域1個と必要帯域7個を比較。倍率と数字を大きく表示する。

### 話すこと

35KiBのパターンを毎秒30回すべて送り直すと、1,050KiB/sが必要です。CD 1倍速の150KiB/sの7倍です。しかも音声や制御データはまだ含めていません。だから、画面全部を毎コマ送り直すのではなく、絵柄の再利用と先読みが必要になります。

## 11. 30fpsは、2回のVBlankで間に合わせる

時間：5:35–6:20

### スライド文言

VBlank＝画面を描画していない短い時間

2回のVBlankをまたぐ表示間隔：約33ms

3回のVBlankをまたぐ表示間隔：約50ms

### 画像のアテ

共通の時間軸で、2周期・約33msと、遅延した3周期・約50msを比較。緑の縦帯をVBlankとする。帯幅は模式表示で、実際のブランキング時間を表す幅ではない。

### 話すこと

VRAMへの転送には、時間の制約もあります。画面を描画していない短い時間をVBlankと呼びます。このプレイヤーでは、画面更新の転送をそこに収めます。表示中にも書き込み自体はできますが、転送できる量が大きく減り、更新途中の絵が見える問題も出ます。NTSCではVBlankが毎秒約60回あります。30fpsなら、2回で次のコマを出す必要があります。3回かかると、そのコマだけ約50ミリ秒表示され、ガクッと見えます。遅れが重なると、先読みデータの置き場も詰まります。CDを読み取り続ける処理まで滞り、再生が崩れる原因になります。

## 12. 転送量が収まっても、時間に収まらない

時間：6:20–7:00

### スライド文言

- DMAの設定と完了待ちにも時間がかかる
- 小分けの転送が多いと、手間が積み重なる
- VBlankの途中から始めると、使える時間が減る

何バイト送るかに加え、いつ始めて何回送るか

### 画像のアテ

同じ転送データ量を2本の横棒で比較。小分け転送ではオレンジの設定時間が繰り返され、VBlankの締切を越える。実測値ではなくコストの関係を示す模式図。

### 話すこと

ここはかなり苦労しました。最初は大きなDMAがVBlankからはみ出していたので、収まる量に分割しました。ところが、小さく分ければよいわけでもありません。転送設定や完了待ちの手間が、回数分かかります。設定の計算を画面表示中に先に済ませたり、ネームテーブルをまとめてDMA転送したりしました。処理の順番を変えたら、逆に待ち時間が増えて悪化した案もあります。転送量を見るだけでは原因が分からず、画面の何ライン目で準備が終わり、どのVBlankで何を転送したかまで計測しました。

### 制作メモ

根拠：f811522（7/8、VBlank内にDMAを分割）、7e80d4f・56adaa2（7/22、DMA設定の前処理化とネームテーブルDMA）、28f1788・9708d3f（7/28、VBlank境界での分割とCPU書き込みコスト計上）、cdc4ca1（7/30、VBlank途中開始DMAの実測）。実験と否定された仮説はharness/cold_cap_model/README.mdを参照。後の計測で否定された通常フレームの位相ラチェット仮説を、確定原因として紹介しない。

## 13. ここからはエンコーダーの話

時間：7:00–7:25

### スライド文言

プレイヤー側の最適化も重要だった。

エンコーダー側は、それ以上に重要だった。

PC上で、何を・いつ・どこへ送るかを決める

### 画像のアテ

なし。大きな文字のセクション切り替え。

### 話すこと

ここまでは、メガCDで動くプレイヤーの話でした。ここからは、PC上で再生用データを作るエンコーダーの話です。プレイヤー側の最適化も重要でしたが、エンコーダー側はそれ以上に重要でした。再生側を速くしても、2回のVBlankに収まらない仕事を渡せば間に合いません。再生前に、送る仕事の量と形を整える必要がありました。

## 14. タイルパターンの再利用

時間：7:25–7:55

### スライド文言

| 画面の状態 | エンコーダーの判断 |
|---|---|
| そのままでよい | 更新しない |
| VRAMに使えるパターンがある | 再利用する |
| 似たパターンで十分 | 近いもので再現する |
| 新しいパターンが必要 | 転送量を割り当てる |

### 画像のアテ

4行の判断図。上3行は更新しない、同じ絵柄を再利用、似た絵柄を再利用。最下段は同じ絵柄を左右に置かず、「転送データ 32 B」から新しいタイルがVRAMへ入る図にする。

### 話すこと

エンコーダーは各フレームを調べ、新しく送る必要がある場所を選びます。同じパターンがあれば再利用し、近いもので十分ならそれを使う。新しく送るのは、そこに転送量を使う価値がある場所です。どこを更新すると映像がよく見えるか。その判断が画質を左右します。

## 15. 先読みバッファのスケジュールもエンコード時に決定

時間：7:55–8:25

### スライド文言

1フレーム目の再生前に、すべてのバッファを埋める

再生に余裕があるときの補充データも、あらかじめ決めてCD 1×に載せる

エンコード時に決めることで、遠い未来に使うパターンも先読みできる

### 画像のアテ

3つの文を、行間と余白を広く取って配置する。下部に「再生前に埋める→余裕のある場面で補充→遠い未来のコマで使う」という小さな模式図を添える。

### 話すこと

先読みのスケジュールも、動画全体を見られるエンコーダー側で決めます。再生前には、各バッファに割り当てた先読み領域を、開始時の予定量まで埋めておきます。余裕のある場面で補充するデータもあらかじめ決め、CD 1倍速の帯域に収まるように収録します。未来のコマまで分かっているため、ずっと先で使うパターンも先にためておけます。

## 16. 計算しない。計算しておく：ADPCM音声

時間：8:25–8:40

### スライド文言

最後に足りなかった資源はCPU時間

ADPCMはPCM音源でそのまま鳴らせない

繰り返す計算 → 用意済みの表を引く
Sub PRG-RAMのルックアップテーブル → PCMサンプル

### 画像のアテ

ADPCMの4ビット符号とステップ番号→Sub PRG-RAMの差分表・次ステップ表→Sub CPUで加算と範囲制限→出力変換表→PCM RAM→PCM音源。計算の全廃ではなく、繰り返す計算の一部を表引きに置き換える図。

### 話すこと

表引き後の加算・範囲制限・PCM RAMへの書き込みはSub CPUが行います。安定した再生のために最後に足りなかったのはCPU時間でした。メガCDはPCM音源なので、ADPCMデータをそのまま鳴らせません。展開で繰り返す計算を減らすため、Sub PRG-RAMに一式のルックアップテーブルを用意しました。必要な結果を表から引くことで、再生時の計算量を減らしました。

## 17. 絵柄と配置は、別々に持っている

時間：8:40–9:10

### スライド文言

パターンテーブル：番号付きの絵柄一覧。1パターン＝8×8ドット。

ネームテーブル：各マスに絵柄の番号を記録。同じ番号を何度でも使える。

どちらもVRAMに保存し、VDPが番号を読んで絵柄を並べる。

映像の更新では、必要な絵柄と配置表をVRAMへ転送する。この転送をまとめて行う仕組みが、次に説明するDMA。

### 画像のアテ

承認済みプレビューをそのまま使用。草・空・雲の3パターンに1〜3の番号を付け、4×3マスのネームテーブルと対応する画面を並べる。実際のH40表示は40×28マスであることを注記。画像：/dev/shm/segacd-fmv-cavc/presentation/proposals/tables-preview.png。

### 話すこと

パターンテーブルは8×8ドットの絵柄を持ち、ネームテーブルは画面のどの位置にどの絵柄を置くかを持ちます。同じ番号を何度も参照できるので、同じ絵柄を繰り返すたびに絵柄そのものを増やす必要はありません。どちらもVRAMに置き、VDPが組み合わせて画面にします。配置表にはパレットや反転の指定も含まれますが、この図では絵柄と配置の関係に絞っています。次のスライドでは、これらを転送するDMAの設定値を事前に作る話につなぎます。

## 18. 絵柄の置き場所が散ると、DMAが増える

時間：約30秒

### スライド文言

送るのは同じ4パターン。違うのは、VRAM上の転送先。

連続した空きへ配置：DMA 1回。飛び飛びの空きへ配置：DMA 4回。

転送量は同じ128バイトでも、設定・開始・完了待ちが増える。

VBlank内に収めるには、バイト数だけでなく「DMAの回数」も重要。

### 画像のアテ

承認済み比較図をそのまま使用：/dev/shm/segacd-fmv-cavc/presentation/proposals/fragmentation-preview.png。RAMの連続したA〜Dを、左ではVRAMの40〜43番へ、右では40・42・44・46番へ転送。灰色は保持中のパターン。1パターン32バイトで、VBlank境界の分割や転送後の補正は省略した模式例。

### 話すこと

再利用するパターンをVRAMに残すと、新しいパターンを置ける位置が飛び飛びになる場合があります。保持中の絵柄を上書きせずに転送するため、連続したひとまとまりでは送れなくなります。この図では同じ128バイトでも、まとめて送れる場合は1回、飛び飛びの場合は4回です。転送元は連続しており、VBlank境界の分割を含めない例です。回数が増えると、転送の設定や完了待ちも増えます。そのため、エンコーダーでは転送量だけでなく、配置と転送のまとまりも考える必要があります。次に、そのDMA設定を事前計算する話へ進みます。

## 19. 計算しない。計算しておく：DMAアドレス

時間：8:40–8:55

### スライド文言

PCで転送元RAM・転送先VRAMのアドレスを事前計算

計算結果をストリームに収録

実機は値を読んでVDPに設定

まじでメガドライブ＋メガCD専用Codec

### 画像のアテ

PCで転送元RAM・転送先VRAM・転送量を決定→VDP設定値をストリームへ格納→Main CPUが値を読んでVDPへ設定しVBlank内でDMA、の3段階。パターン本体のWORD-RAM／MAIN-RAM→VDP→VRAMという経路も別に示す。

### 話すこと

DMAにはRAMの転送元とVRAMの転送先アドレスが必要です。再生中に計算せず、エンコード時にあらかじめ求めて、結果をストリームに入れます。プレイヤーは用意された値を読み、VDPへ設定する。PC側で仕事を済ませて実機のCPU時間を節約します。まじでメガドライブとメガCDに専用のCodecです。

## 20. 人間の仕事：最適化構造の洗い出し

時間：9:25–9:50

### スライド文言

最適化構造の洗い出し

### 画像のアテ

構造を考える、AIと実装、計測して確かめる、をループ図で結ぶ。上段の3列説明は削除し、ループ図を中央に配置する。合意済みの短い発表原稿は変更しない。

### 話すこと

もう一つが、最適化構造の洗い出しです。

どこにデータを残せば転送を減らせるか。
どの処理を先に済ませられるか。
使う順番を変えれば、メモリをもっと有効に使えないか。

AIと実装・計測を繰り返しながら、その構造を探しました。

### 制作メモ

合意した短い原稿のみ。制約撤回のプロンプトや、自分のミスの話は入れない。

## 21. エンコード結果と再生時の実測ログのタイムライン化

時間：9:50–10:10

### スライド文言

エンコード結果と再生時の実測ログのタイムライン化

### 画像のアテ

既存のSonic Jam OP e171/p144 mixlineを、元のヘッダーと判定を含む全体画像で挿入する。タイトル以外のラベル、矢印、キッカー、フッター、ページ番号は置かない。出典：https://gist.github.com/akiyan/f81d473dbde22a7a5699efcb03ca302d 。当時の記録の引用であり、新しい検証結果ではない。

### 話すこと

最適化の結果は、mixlineという画像で確認しました。上側にエンコーダーの判断、下側にエミュレータ再生時の計測値を、同じフレーム軸で並べています。次のスライドで全指標を紹介します。

## 22. mixline の全指標

時間：10:10–10:30

### スライド文言

エンコーダー：REQ、SUPPLY、RUN、R2V、DIC、BAND

プレイヤー：VBLANK、PATTERN READY PRESSURE、NT READY PRESSURE、SECTOR SLIP、CONTROL DESYNC、AUDIO RESYNC、VBLANK SPILL、PRGBUF JITTER、SUB PUMP GAP、MSF GAP、APPLY BACKPRESSURE、READER AHEAD、READER SLOT、TRANSFER VBLANKS、TRANSFER END、CD WAIT、AUDIO LEAD、SUB HANDOFF、ADPCM、PATTERN TRANSFER、COLD RUNS、FLIP VCOUNTER、FIRST SHARE EXIT、PASS2 DELAY

### 画像のアテ

表示中のmixlineに対応するtimeline-layoutとhudline-layoutの全30行を3列の表にする。各指標に、日常語による1行の短い説明を付ける。文字は多少小さくてよい。

### 話すこと

mixlineは、エンコーダー側の6指標と、プレイヤー側の24指標をまとめています。表は、それぞれの行を読むための短い案内です。REQの中にはRaw、Same、Near、Flbk、Miss、Prg、Wrd、Dicという判断の内訳もあります。名称と単位は、表示中のmixlineに対応する機械可読のレイアウト記録から取得しています。

### 制作メモ

定義の出典：logs内のSonic Jam OP e171/p144に対応するtimeline-layoutとhudline-layout JSON。

## 23. 特に重要だった4つの指標

時間：10:35–11:00

### スライド文言

VBLANK：表示周期
30fpsで2回に収まったか。表示が遅れたコマを特定する。

R2V：VRAMへの転送量
予定した転送量と実測の遅れを比較。量が多いのか、準備や転送の手間なのかを切り分ける。

PRGBUF JITTER：バッファの余裕
揺れ吸収用の余白を最大でどれだけ使ったか。エンコーダーに使わせず残す余裕を決める。

ADPCM：音声に使うCPU時間
Sub CPUの音声展開時間を測る。CD読み込みや次コマ準備に時間を残せるかを確認する。

### 画像のアテ

4行で指標名・測る対象・何の判断に効くかを対応させる。装飾的な画像は使わない。

### 話すこと

VBLANKでは、狙った表示周期から外れたコマを見つけます。R2Vは予定した転送量なので、再生時の遅れと重ねることで、量の問題なのか、CPUの準備や転送ごとの手間なのかを切り分けます。PRGBUF JITTERは、揺れを吸収する余白を使った最大値で、現在の残量ではありません。物理バッファをエンコーダーが使い切らないための余裕を判断します。ADPCMではSub CPUの音声展開時間を確認し、CDの取り込みやコマの受け渡しと両立できるかを見ます。一つだけで原因と決めず、同じコマで重ねて読みます。

## 24. プロンプト実例：VBlankの仮説

時間：10:30–11:10

### スライド文言

> H40 Bad Apple を cold240 にしたとき、SLIPが発生して HUD gate がFAILになったあと、以下のやりとりがあった。
>
> run fragmentationより、転送量が境界を越えて次のVBlankを待った形 30fpsだと1フレームの処理に2VBlankが使えて、最初のVBLANKと次のVBLANKがある。現在、最初のrunやCPU転送は最初のVBLANK前から行われうる？それとも前処理次第では、CPUもDMArunも最初のVBLANKでは行われず、次のVBLANKに集約されてしまったりする？

出典：PROMPTS.md、第7節。

### 画像のアテ

引用原文を、行間と余白を広く取った簡潔な汎用プロンプト入力フォームの中に置く。右に2回のVBlank枠を置き、前処理が最初の枠に間に合わず、2回目へ転送が集まる可能性を問う時間図にする。

### 話すこと

自分の仮説を持ち込むこともありました。ここでは、転送の分割数だけでなく、前処理のタイミングによって30fpsで使える最初のVBlankを逃していないか、と問いかけています。

## 25. プロンプト実例：パレットの黒を例外扱い

時間：11:10–11:50

### スライド文言

> 黒点に加えて輝点まで目立つようになってしまった。多候補混合は無しだ。
>
> ただ、重要な事実を気づかせてくれた。
>
> 「全パレット行が強制的に持っている黒エントリ」
>
> これはメガドライブのパレットの仕様からくる歪んだパレット色そのもので、今回の問題の要因とも言えそう。この黒パレットは固定なので、例外として扱うべきだ。ただ、「使わない」というのはもったいないので、パレット選定アルゴリズムが非常に深い黒を欲しがった場合は使えばいい。必要だから。SonicOPはおそらく欲しがっていないのに存在するから、2色混合で選ばれてしまうのではないか。そのパレット16色(15色)において欲しがられなかった非常に深い黒は、色再現時の道具としては「無いもの」として扱うようにしたい。

出典：PROMPTS.md、第1節。

### 画像のアテ

引用原文を同じ汎用フォームの中に置く。右に16色×4本のパレットを置き、各行に強制的に入る黒だけを囲む。深い黒が必要な区間だけ使用し、不要な区間では色再現の候補から外す判断を図で示す。

### 話すこと

メガドライブでは、各パレット行に固定の黒があります。映像が深い黒を必要としていないのに、この固定色を通常の混色候補として使うと、黒点や輝点の原因になります。例外として扱いつつ、本当に深い黒が必要なときだけ使えるようにする条件まで伝えています。

## 26. プロンプト実例：つぶれた顔を追う

時間：11:50–12:30

### スライド文言

> machi op の F067D の人物（左上）の顔がつぶれてしまってシーン切り替わりまで残ってしまい気になる。右下の顔は動いているので自然と更新対象になりつぶれが解消するが、左上は変化が無いためNear判定でそのままつぶれた感じがシーン切り替わりまで持続してしまう。cold優先度のロジックの調整か何かで解決したい。推測だが、最初にこのシーンが出る際のcold対象タイルの選定時点で「変化が大きいタイル」で測っていると思うが、シーンの切り替わりのため、全てどれも変化が最大近くになってしまっているのではないだろうか。あるいは僅差。まずはなぜこの顔のほうがcoldになっていないのか確認しよう。現行データから当該フレームの情報を持ってきて確認。（再simなどはしないで）

出典：PROMPTS.md、第8節。

### 画像のアテ

引用原文を同じ汎用フォームの中に置く。右に「顔がつぶれる → 人物が動かない → Near判定で場面転換まで残る」の3段階を示す模式図を置く。

### 話すこと

具体的なフレームと顔の位置、動く顔との違い、Near判定で崩れが残る時間、cold優先度への仮説をまとめています。さらに、再simをせず現行データから原因を調べるところまで作業条件を指定しています。

## 27. プロンプト実例：H40に絞る

時間：12:30–13:10

### スライド文言

> H32は画面にたいしてドットが大きく、容量を節約できる面があることを期待していたが、ドットが大きくてディザ表現するととても荒く感じてしまい、結局どれもH40を採用してしまっている。DMA帯域も減るため、cold制限もきつくて、タイルが少なくて済んでも転送できるタイル数が少なくなってしまう。
>
> mode4についてもBG1面とスプライトしか使えず、Windowが無い。DMAを使うにはVBLANK中にmode5との切り替えが必要になり、VBLANK超過は絶対にしてはいけなさそうで、実装難易度やビルド分岐を考えると、H40専用のCodecにしてしまおうと思う。

出典：PROMPTS.md、第2節から抜粋。

### 画像のアテ

引用原文を同じ汎用フォームの中に置く。右にH32とH40のタイル格子を置き、H32はドットが大きい一方、DMA帯域も少ないという判断を図で示す。

### 話すこと

画質とハードウェア制約の両方から、製品の範囲そのものを決めた指示です。H32はタイルが少なくて済みますが、ディザが荒く見え、VDPが転送できる量も減ります。利点と欠点を比べ、コーデックをH40専用にする判断を伝えました。

## 28. プロンプト実例：実機だけで音が荒れる

時間：13:10–14:25

### スライド文言

> アナログ系のノイズではなく音源へのデジタル系の実機だけで起きる問題です。
>
> また、MEGA EVERDRIVE PRO から iso 起動した場合はまったくノイズが出ずクリアです。MEGA EVERDRIVE PROは内部にメガCDの回路を持っているけど実機と挙動が異なりそうですね。biosはこのメガCD2から抽出したbiosをMEGA EVERDRIVE PROで使っているので、bios差もありません。
>
> CD-Rを何度も焼きたくないので、情報を探すなどして正確性の高い対処を行いたいです。

出典：PROMPTS.md、第3節から抜粋。

### 画像のアテ

日本語原文の抜粋を同じ汎用フォームの中に置き、右に同じBIOSでの比較図を置く。実機メガCDはノイズあり、MEGA EVERDRIVE PROはクリアと示す。

### 話すこと

最後の実機音声の詰めです。実機メガCDではノイズが出るのに、メガCD機能を持つMEGA EVERDRIVE PROでは出ない。BIOSも同じです。比較条件と分かっていることを指示に含め、次に何を調べるかを相談しました。

## 29. ご清聴ありがとうございました！

時間：14:25–15:00

### スライド文言

ご清聴ありがとうございました！

### 画像のアテ

なし。大きな謝辞だけを表示する。

### 話すこと

ありがとうございました。
