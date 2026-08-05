# YouTube upload text checker

[`YOUTUBE.md`](../../YOUTUBE.md) states the rules for a codec video's title and
description. This harness checks a candidate title and description against
those rules before the upload happens.

It exists because prose rules did not hold in practice. A description went out
at 5,122 characters, four titles lost their `eN.pM` suffix to YouTube's
100-character cut, links were duplicated into the Japanese half, and a playback
description named analysis panels that are not on its screen. Every check below
corresponds to one of those failures.

## Run

```sh
tools/python.sh harness/youtube_description/check_upload_text.py \
  DESCRIPTION.txt --kind analysis|playback|verification \
  --title "SEGA-CD FMV of ... 20260805.e190.p152" \
  --cross-link https://youtu.be/OTHER_KIND
```

The checker reads only; it never edits the text. It prints every failure in one
pass and exits non-zero when any remain, so one run is enough to fix
everything. Exit zero with `WARN` means the text is uploadable but above the
4,800-character working target.

Pass `--allow-missing-cross-link` for the first upload of an encode, before its
counterpart exists. Add the link and re-check once the other video is up.

## What it checks

Title:

- at most 100 characters, the point where YouTube truncates;
- matches the profile's `[youtube] analysis_title` / `playback_title` exactly
  when `--profile-title` is given;
- carries no build version and no `vNNN` sequence version. The version lives on
  the description's closing Build line.

Description, both kinds:

- at most 5,000 characters, warning above the 4,800 target;
- no `<` or `>`, which YouTube rejects as `invalidDescription` (HTTP 400);
- an English half, a `----` separator, and a Japanese half;
- no URL anywhere in the Japanese half;
- the public codec name and the project link present;
- a CRAM palette switch count present;
- a closing `Build: YYYYMMDD.eN.pM` line, last in the English section, matching
  `--build` when given. Since the title carries no version, this line is the
  only record of which build the video shows;
- no build-system wording. "release build", "DEBUG build", "debug overlay",
  and "DEBUG HUD" describe how the artifact was compiled, which the viewer
  neither knows nor needs; say what is on screen instead. The title is checked
  for the same terms;
- no changelog wording. The list covers "no longer", "previously", "instead of
  before", "improved", "regressed", "this version adds/fixes/changes",
  "compared to the previous", and the Japanese equivalents. A description
  states what this build is, never how it differs from another.

Description, playback only:

- no analysis-only vocabulary. A playback recording has no category map, no
  legend, no meters, and no timelines, so naming them misleads the viewer.

Verification uploads (`--kind verification`) are diagnostic records, not
published works, so none of the public rules apply. The checker requires only
that the title and description carry the build version, that the description is
not empty, and that it fits YouTube's limits. Describing what changed is
expected there.

## What it deliberately does not check

Content correctness. The checker cannot tell whether the stated grid, pattern
counts, or CRAM count match the encode; read those from the sim output and
`tools/cram_switches.py`. Two wrong numbers reached a live description this
way, so verify them by hand until this harness learns to read `decisions.pkl`.
It also cannot judge whether an explanation is actually understandable.
