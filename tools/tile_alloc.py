"""Shared VRAM tile-slot allocator — the SINGLE source of the cold/reuse decision.

Both the encoder (``tools/sim.py``) and the packer (``tools/pack_stream.py``) must
agree on *which* tiles are resident in VRAM each frame, because that is what decides
"cold" (a fresh 32-byte pattern load) vs "reuse" (a name-table pointer to a resident
slot). Historically they each ran their own residency model — the sim an LRU dict, the
pack a contiguous clock-hand allocator — so the pack "realized" a few more cold loads
than the sim modelled (e.g. sim cap 350 -> pack realized 357). Even with matching
*policy names* the two implementations diverged (contig +7, lru +5), because a
re-derived allocation is never bit-identical.

The fix: one allocator, imported by both. When the sim caps its per-frame cold at
the profile cold cap using THIS allocator, and the pack replays the SAME allocator on
the SAME per-frame update order, the pack's realized cold equals the sim's cap by
construction. So ``COLD_CAP_REALIZED`` collapses into the single profile cap.

Policy: **contiguous** (a clock hand walks the slot ring), which keeps cold tiles in
neighbouring VRAM slots so the Main CPU can DMA them in long runs. Displayed tiles
(referenced by a cell this or last frame) are protected from eviction.
"""

import numpy as np


def cold_transfer_order(placements):
    """Return cold update indices sorted by ascending physical VRAM slot.

    Name-table updates remain in cell order.  The v12 run suffix already
    separates the transfer list from those updates, so payload order is free to
    follow physical slots and form the longest possible runs for a fixed slot
    set.
    """
    return tuple(sorted(
        (index for index, (_slot, cold) in enumerate(placements) if cold),
        key=lambda index: (int(placements[index][0]), index),
    ))
def slot_runs(slots):
    """Return ascending consecutive VRAM-slot runs in payload order.

    Each result is ``(slot_start, tile_count)``.  The caller supplies cold slots
    only, so reuse entries do not split a run.  A pool wrap is not consecutive:
    ``pool - 1`` followed by ``0`` starts a new run, just like the player.
    """
    runs = []
    for slot in slots:
        slot = int(slot)
        if runs and runs[-1][0] + runs[-1][1] == slot:
            start, count = runs[-1]
            runs[-1] = (start, count + 1)
        else:
            runs.append((slot, 1))
    return runs


def count_slot_runs(slots):
    """Count the packed/player cold-run records for a cold-slot sequence."""
    return len(slot_runs(slots))


class FrameTransitionGuard:
    """Reserve the extra VRAM identities needed by one display transition.

    Pattern loads finish before the final name-table DMA, so every slot used
    by the preceding display remains live while the next display is prepared.
    A selected key needs one additional slot unless its resident slot is
    already part of that preceding display. The encoder may replace an
    earlier choice for the same cell, so this guard reference-counts selected
    keys and releases a no-longer-used reservation.

    Construct the guard before making a frame's decisions and do not mutate
    the allocator until those decisions are complete.
    """

    def __init__(self, allocator):
        self._allocator = allocator
        self.capacity = int(
            allocator.POOL - np.count_nonzero(allocator.slot_refs))
        self._cell_key = {}
        self._extra_refs = {}

    @property
    def used(self):
        return len(self._extra_refs)

    def _needs_extra_slot(self, key):
        slot = self._allocator.key_slot.get(key)
        return slot is None or self._allocator.slot_refs[slot] == 0

    def fits(self, cell, key):
        """Return whether selecting ``key`` for ``cell`` fits the transition."""
        cell = int(cell)
        old_key = self._cell_key.get(cell)
        if old_key == key:
            return True
        used = self.used
        if (old_key is not None
                and self._needs_extra_slot(old_key)
                and self._extra_refs[old_key] == 1):
            used -= 1
        if (self._needs_extra_slot(key)
                and key not in self._extra_refs):
            used += 1
        return used <= self.capacity

    def commit(self, cell, key):
        """Record one accepted selection, replacing that cell's prior choice."""
        cell = int(cell)
        if not self.fits(cell, key):
            raise RuntimeError(
                "frame transition exceeds the VRAM slots outside the "
                "preceding display")
        old_key = self._cell_key.get(cell)
        if old_key == key:
            return
        if old_key is not None and self._needs_extra_slot(old_key):
            remaining = self._extra_refs[old_key] - 1
            if remaining:
                self._extra_refs[old_key] = remaining
            else:
                del self._extra_refs[old_key]
        self._cell_key[cell] = key
        if self._needs_extra_slot(key):
            self._extra_refs[key] = self._extra_refs.get(key, 0) + 1


class TileAllocator:
    """Slot residency for one stream. Feed it each frame's updated cells in a fixed
    order; it assigns a VRAM slot per tile key and reports cold (new load) vs reuse.

    ``c_cells`` = grid cell count, ``pool`` = resident VRAM slot count, ``base`` =
    ``POOL_TILE_BASE`` (VRAM tile index of slot s = base + s).
    """

    def __init__(self, c_cells, pool, base=1):
        self.C_CELLS = int(c_cells)
        self.POOL = int(pool)
        self.BASE = int(base)
        self.key_slot = {}                                   # tile key -> slot
        self.slot_key = [None] * self.POOL                   # slot -> tile key
        self.slot_refs = np.zeros(self.POOL, np.int32)       # cells currently showing slot
        self.slot_lastuse = np.full(self.POOL, -1, np.int64)
        self.free = list(range(self.POOL - 1, -1, -1))       # so pop() hands out 0,1,2… ascending
        self.hand = 0                                        # clock hand (contig)
        self.tearing = 0                                     # evictions forced past protection
        self.cur_slot = np.full(self.C_CELLS, -1, np.int64)  # cell -> slot it currently shows
        self.prev_slot = np.full(self.C_CELLS, -1, np.int64) # cell -> slot last frame (protect)
        self._prev_protect = np.zeros(self.POOL, bool)
        self._tfp = None                                     # this-frame reuse-tile protection
        # A raw-prefetched pattern has no cell reference yet.  Keep its slot
        # until the first planned use so the ordinary clock hand does not
        # immediately recycle it.  The feature is inert when every value is -1.
        self.slot_pin_until = np.full(self.POOL, -1, np.int64)
        # Ordinary prediction is deliberately speculative: visible work may
        # reclaim it.  A detected fade reference is different because its
        # later CRAM-only frames cannot repair missing pattern data.  Mark
        # those pins mandatory so normal allocation preserves them through
        # the reference frame's first real use.
        self.slot_pin_mandatory = np.zeros(self.POOL, bool)
        self.pinned_count = 0
        self.prefetch_evictions = 0
        self.mandatory_prefetch_evictions = 0
        self.prefetch_cache_evictions = 0

    # ---- residency query (used by the sim for cold/reuse + resident matching) ----
    def is_resident(self, key):
        return key in self.key_slot

    def resident_slot(self, key):
        """Return the physical slot for ``key``, or ``None``."""
        return self.key_slot.get(key)

    def resident_keys(self):
        return self.key_slot.keys()

    def is_pinned(self, key, deadline):
        """Return whether ``key`` is protected through ``deadline``."""
        slot = self.key_slot.get(key)
        return slot is not None and self.slot_pin_until[slot] >= int(deadline)

    def is_mandatory_pinned(self, key, deadline):
        """Return whether ``key`` has a catch-up-protected fade pin."""
        slot = self.key_slot.get(key)
        return (
            slot is not None
            and bool(self.slot_pin_mandatory[slot])
            and self.slot_pin_until[slot] >= int(deadline)
        )

    def least_live_contiguous_block(self, length, frame_idx):
        """Return a linear slot block with the fewest live occupants.

        Mandatory fade references use one shared edge block so their long-lived
        pins do not split ordinary cold allocations into many one-tile DMA
        runs.  Of the low and high edge blocks, current plus preceding display
        occupancy is the second tie-break after active mandatory pins; a
        stable low-edge tie-break keeps sim replay deterministic.
        """
        length = int(length)
        frame_idx = int(frame_idx)
        if not 0 < length <= self.POOL:
            raise ValueError("contiguous block length is outside the pool")
        mandatory = np.logical_and(
            self.slot_pin_mandatory,
            self.slot_pin_until >= frame_idx,
        ).astype(np.int64)
        live = np.logical_or(
            self.slot_refs > 0,
            self._prev_protect,
        ).astype(np.int64)
        mandatory_prefix = np.concatenate(([0], np.cumsum(mandatory)))
        live_prefix = np.concatenate(([0], np.cumsum(live)))
        best = None
        starts = (0,) if length == self.POOL else (0, self.POOL - length)
        for start in starts:
            stop = start + length
            score = (
                int(mandatory_prefix[stop] - mandatory_prefix[start]),
                int(live_prefix[stop] - live_prefix[start]),
                start,
            )
            if best is None or score < best[0]:
                best = score, start
        return int(best[1])

    def _forced_prefetch_slot_available(
            self, slot, frame_idx, avoid_keys=()):
        """Return whether a cold prefetch may replace ``slot`` now."""
        slot = int(slot)
        frame_idx = int(frame_idx)
        if not 0 <= slot < self.POOL:
            raise ValueError("forced prefetch slot is outside the pool")
        if slot in self.free:
            return True
        if not isinstance(avoid_keys, (set, frozenset)):
            avoid_keys = set(avoid_keys)
        return not (
            self.slot_refs[slot] != 0
            or self._prev_protect[slot]
            or (self._tfp is not None and self._tfp[slot])
            or self.slot_key[slot] in avoid_keys
            or (
                self.slot_pin_mandatory[slot]
                and self.slot_pin_until[slot] >= frame_idx
            )
        )

    def find_prefetch_slot_in_block(
            self, key, frame_idx, block_start, block_length,
            assigned_slots=(), avoid_keys=()):
        """Choose a safe destination inside a reserved contiguous block.

        A reference key already resident inside the block stays in place,
        including while displayed, because upgrading its pin writes no VRAM.
        New or relocated keys use the first currently safe unassigned slot.
        This preserves one compact fade region without making each key wait
        for one fixed destination that may still belong to the live display.
        """
        block_start = int(block_start)
        block_length = int(block_length)
        block_stop = block_start + block_length
        if block_length <= 0 or block_start < 0 or block_stop > self.POOL:
            raise ValueError("prefetch block is outside the pool")
        assigned = set(int(slot) for slot in assigned_slots)
        resident = self.key_slot.get(key)
        if (resident is not None
                and block_start <= int(resident) < block_stop
                and int(resident) not in assigned):
            return int(resident)
        for slot in range(block_start, block_stop):
            if slot in assigned:
                continue
            if self._forced_prefetch_slot_available(
                    slot, frame_idx, avoid_keys=avoid_keys):
                return int(slot)
        return None

    def prefetch_mandatory_in_block(
            self, key, frame_idx, deadline, block_start, block_length,
            assigned_slots=(), avoid_keys=()):
        """Pin a fade key, preferring cold placement in one shared block.

        Moving an already-resident reference would turn a free warm pin into a
        redundant cold transfer, so keep it in place.  A new key uses the
        first safe unassigned slot in the block.  If every block destination
        is still part of a live display, fall back to the allocator's normal
        safe cache search rather than waiting or overwriting visible VRAM.

        Returns ``(slot, cold, relocate, forced)`` or ``None``.  The last two
        values reproduce the exact allocator operation during pack replay.
        """
        resident = self.key_slot.get(key)
        if resident is not None:
            slot, cold = self.prefetch(
                key,
                frame_idx,
                deadline,
                mandatory=True,
            )
            return int(slot), bool(cold), False, False

        forced_slot = self.find_prefetch_slot_in_block(
            key,
            frame_idx,
            block_start,
            block_length,
            assigned_slots=assigned_slots,
            avoid_keys=avoid_keys,
        )
        if forced_slot is not None:
            result = self.prefetch(
                key,
                frame_idx,
                deadline,
                forced_slot=forced_slot,
                avoid_keys=avoid_keys,
                mandatory=True,
                relocate=True,
            )
            if result is not None:
                slot, cold = result
                return int(slot), bool(cold), True, True

        result = self.prefetch(
            key,
            frame_idx,
            deadline,
            avoid_keys=avoid_keys,
            mandatory=True,
        )
        if result is None:
            return None
        slot, cold = result
        return int(slot), bool(cold), False, False

    # ---- per-frame ----
    def begin_frame(self):
        """Compute which slots are protected (a cell showed them last frame)."""
        self._prev_protect[:] = False
        ps = self.prev_slot[self.prev_slot >= 0]
        self._prev_protect[ps] = True

    def _evict(self, s):
        k = self.slot_key[s]
        if k is not None:
            self.key_slot.pop(k, None)
            self.slot_key[s] = None
        if self.slot_pin_until[s] >= 0:
            self.pinned_count -= 1
        self.slot_pin_until[s] = -1
        self.slot_pin_mandatory[s] = False

    def _alloc_slot_contig(self, frame_idx):
        # Clock hand: free slot first. A visible update then reclaims a
        # speculative prefetch before evicting any ordinary resident cache
        # entry, so speculation cannot make the baseline cache smaller.
        if self.free:
            return self.free.pop()
        if self.pinned_count:
            for _ in range(self.POOL):
                s = self.hand
                self.hand = (self.hand + 1) % self.POOL
                if self.slot_refs[s] == 0 and not self._prev_protect[s] and \
                   (self._tfp is None or not self._tfp[s]) and \
                   self.slot_pin_until[s] >= frame_idx and \
                   not self.slot_pin_mandatory[s]:
                    self.prefetch_evictions += 1
                    self._evict(s)
                    return s
        for _ in range(self.POOL):
            s = self.hand
            self.hand = (self.hand + 1) % self.POOL
            if self.slot_refs[s] == 0 and not self._prev_protect[s] and \
               (self._tfp is None or not self._tfp[s]) and not (
                   self.slot_pin_mandatory[s]
                   and self.slot_pin_until[s] >= frame_idx):
                self._evict(s)
                return s
        # Keep fade-reference pins ahead of ordinary cache history, but never
        # sacrifice a visible update or a key reused later in this same frame.
        # If the moving display temporarily needs the whole pool, release one
        # pin and let the fade catch-up queue restore it after the visible
        # updates have finalized.
        if self.pinned_count:
            for _ in range(self.POOL):
                s = self.hand
                self.hand = (self.hand + 1) % self.POOL
                if self.slot_refs[s] == 0 and \
                   (self._tfp is None or not self._tfp[s]) and \
                   self.slot_pin_mandatory[s] and \
                   self.slot_pin_until[s] >= frame_idx:
                    self.mandatory_prefetch_evictions += 1
                    self._evict(s)
                    return s
        self.tearing += 1
        for _ in range(self.POOL):
            s = self.hand
            self.hand = (self.hand + 1) % self.POOL
            if self.slot_refs[s] == 0 and not (
                    self.slot_pin_mandatory[s]
                    and self.slot_pin_until[s] >= frame_idx):
                self._evict(s)
                return s
        candidates = np.flatnonzero(np.logical_not(np.logical_and(
            self.slot_pin_mandatory,
            self.slot_pin_until >= frame_idx,
        )))
        if not len(candidates):
            raise RuntimeError(
                "VRAM has no slot outside mandatory fade prefetch")
        s = int(candidates[np.argmin(self.slot_lastuse[candidates])])
        self._evict(s)
        return s

    def place(self, cell, key, frame_idx):
        """Ensure ``key`` has a slot; record that ``cell`` now shows it.
        Returns ``(slot, cold)`` where cold=True means a fresh pattern load."""
        cold = key not in self.key_slot
        if cold:
            slot = self._alloc_slot_contig(frame_idx)
            self.key_slot[key] = slot
            self.slot_key[slot] = key
        else:
            slot = self.key_slot[key]
            # The prefetched pattern has reached a real display use.  Ordinary
            # current/previous-frame reference protection takes over now.
            keep_mandatory = (
                bool(self.slot_pin_mandatory[slot])
                and frame_idx < int(self.slot_pin_until[slot])
            )
            if not keep_mandatory:
                if self.slot_pin_until[slot] >= 0:
                    self.pinned_count -= 1
                self.slot_pin_until[slot] = -1
                self.slot_pin_mandatory[slot] = False
        oldc = self.cur_slot[cell]
        if oldc >= 0:
            self.slot_refs[oldc] -= 1
        self.slot_refs[slot] += 1
        self.slot_lastuse[slot] = frame_idx
        self.cur_slot[cell] = slot
        return int(slot), bool(cold)

    def prefetch(
            self, key, frame_idx, deadline, forced_slot=None, avoid_keys=(),
            mandatory=False, relocate=False):
        """Place one future pattern without changing any displayed cell.

        Returns ``(slot, cold)``.  ``cold`` is true only when a 32-byte VRAM
        write is required.  ``None`` means no safely evictable unreferenced
        slot exists; speculative work is skipped rather than tearing display.
        """
        frame_idx = int(frame_idx)
        deadline = int(deadline)
        if deadline <= frame_idx:
            raise ValueError("prefetch deadline must be after the load frame")
        resident = self.key_slot.get(key)
        if resident is not None and (
                forced_slot is None
                or int(forced_slot) == int(resident)
                or not relocate):
            # Ordinary prediction does not pin cache data because changing its
            # eviction priority can make a baseline frame worse.  A fade
            # reference must survive until its CRAM-only sequence starts, so
            # upgrade even an already-resident key to a mandatory pin.
            if mandatory:
                if self.slot_pin_until[resident] < 0:
                    self.pinned_count += 1
                self.slot_pin_until[resident] = max(
                    int(self.slot_pin_until[resident]), deadline)
                self.slot_pin_mandatory[resident] = True
            return int(resident), False

        avoid_keys = set(avoid_keys)
        if forced_slot is not None:
            slot = int(forced_slot)
            if not self._forced_prefetch_slot_available(
                    slot, frame_idx, avoid_keys=avoid_keys):
                return None
            if slot in self.free:
                self.free.remove(slot)
            else:
                self._evict(slot)
                # A forced fade destination is part of a separately managed
                # block.  Redirecting the ordinary allocation hand into that
                # block would make the next visible frame consume its still
                # empty destinations and split otherwise contiguous runs.
                if not mandatory:
                    self.hand = (slot + 1) % self.POOL
        elif self.free:
            slot = self.free.pop()
        else:
            # A full resident cache may still have a safe speculative victim:
            # it must be unreferenced now and in the previous display, must
            # not be another pending prefetch, and must not be needed by the
            # target frame.  This deliberately gives up only cache history;
            # no displayed pattern is overwritten.
            slot = None
            for _ in range(self.POOL):
                candidate = self.hand
                self.hand = (self.hand + 1) % self.POOL
                candidate_key = self.slot_key[candidate]
                if self.slot_refs[candidate] != 0:
                    continue
                # Pattern transfers can span multiple VBlanks.  The preceding
                # frame therefore remains the live display until every
                # pattern and name-table update for this frame has completed.
                # Mandatory fade work must wait too; replacing one of these
                # slots early produces transient 8x8 corruption on playback.
                if self._prev_protect[candidate]:
                    continue
                if candidate_key in avoid_keys:
                    continue
                if self.slot_pin_until[candidate] >= frame_idx:
                    if (not mandatory
                            or self.slot_pin_mandatory[candidate]):
                        continue
                    self.prefetch_evictions += 1
                slot = candidate
                self._evict(slot)
                self.prefetch_cache_evictions += 1
                break
            if slot is None:
                return None

        if resident is not None:
            # Relocate a cache identity into its dedicated fade block.  The
            # old physical bytes may still be on screen, so detach only the
            # lookup identity; slot_refs keeps that old slot protected until
            # every displayed cell has moved away from it.
            if self.slot_key[resident] != key:
                raise AssertionError("resident key/slot mapping diverged")
            self.slot_key[resident] = None
            if self.slot_pin_until[resident] >= 0:
                self.pinned_count -= 1
            self.slot_pin_until[resident] = -1
            self.slot_pin_mandatory[resident] = False

        self.key_slot[key] = slot
        self.slot_key[slot] = key
        self.slot_lastuse[slot] = frame_idx
        self.slot_pin_until[slot] = deadline
        self.slot_pin_mandatory[slot] = bool(mandatory)
        self.pinned_count += 1
        return int(slot), True

    def end_frame(self):
        self.prev_slot[:] = self.cur_slot

    def place_frame(self, cells_keys, frame_idx):
        """Two-pass frame allocation (the disc's true behaviour). ``cells_keys`` = a
        LIST of ``(cell, key)`` in cell order (this frame's updated cells). Pass 1
        protects every reuse tile (already resident) so pass 2's cold allocations
        never evict a tile shown this frame -> no intra-frame reload -> realized cold
        equals the fresh-key count (= the sim's cap). Returns ``[(slot, cold), ...]``
        in the given order. There is always room: a frame shows <= C_CELLS distinct
        tiles and the pool is larger."""
        self.begin_frame()
        tfp = np.zeros(self.POOL, bool)
        for (cell, key) in cells_keys:
            s = self.key_slot.get(key)
            if s is not None:
                tfp[s] = True
        self._tfp = tfp
        out = [self.place(cell, key, frame_idx) for (cell, key) in cells_keys]
        self._tfp = None
        self.end_frame()
        return out
