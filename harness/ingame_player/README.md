# In-game player captures

Diagnostics for the in-game player test disc (`make ingame-disc`,
[`PLAYER.md`](../../PLAYER.md#in-game-player)). Both read the BlastEm VDP
trace of a capture made with `tools/record_movie.sh --vdp-event-log`; neither
reimplements player assembly.

## Playback check

```sh
tools/python.sh harness/ingame_player/check_capture.py "$VDP_EVENT_LOG" \
  --header out/PROFILE/HEADER.DAT --profile profiles/PROFILE.toml \
  --json logs/STEM_check.json
```

For every play it reports one publication per frame, every displayed field
from frame 0 to the end compared with the SIM picture of the latest
publication, VDP writes outside the blank (more than 38 lines after the
movie's VBlank hook entry) or outside the movie's VRAM budget, the VBlank
gaps between publications, and the test host's result rows drawn after the
play. `PASS` needs exact pictures and no write outside the blank or budget in
every complete play. Add `--profile-log` for a diagnostic build, whose VSRAM
log is otherwise counted as outside the budget.

## Main idle time

```sh
make ingame-disc CONFIG=profiles/PROFILE.toml INGAME_PROFILE=1
tools/record_movie.sh --disc out/PROFILE_ingame_profile.cue --no-build \
  --seconds N --tag STEM_profile --vdp-event-log
tools/python.sh harness/ingame_player/idle_report.py "$VDP_EVENT_LOG" \
  --json logs/STEM_idle.json
```

The diagnostic Main module counts the scanlines Main spends in its playback
wait loops (active-display and VBlank lines separately) and writes them to
VSRAM at each VBlank hook entry. The report gives their distribution per
VBlank interval and per movie frame over timed playback, and the worst
intervals and frames. `INGAME_SUBBUS_LOAD=N` also holds the Sub bus for about
N Main cycles in every VBlank, to see whether a music driver's PRG-RAM reads
disturb the Sub side; check such a capture with `check_capture.py`.

Both tools find the plays by the test host's horizontal-interrupt line
setting (register 10) and the movie's plane-B write. `idle_report.py` also
assumes the full 40x28 aperture: the first name-table entry marks a
publication.
