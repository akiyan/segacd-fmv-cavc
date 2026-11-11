"""Admission of optional image work against a packed transfer-run ceiling."""
from copy import copy

import numpy as np

import pattern_supply
from tile_alloc import cold_transfer_order


def clone_allocator(allocator):
    """Copy mutable allocation state without duplicating immutable pattern keys."""
    trial = copy(allocator)
    for name, value in vars(allocator).items():
        if isinstance(value, (dict, list, np.ndarray)):
            setattr(trial, name, value.copy())
    return trial


def count_runs(placements, keys, sources, dictionary, prefetch_slots=()):
    order = cold_transfer_order(placements)
    slots = [int(placements[index][0]) for index in order]
    kinds = [sources.get(keys[index], pattern_supply.SOURCE_PRG) for index in order]
    indices = [dictionary[keys[index]] if source == pattern_supply.SOURCE_DIC
               else -1 for index, source in zip(order, kinds)]
    suffix = sorted(int(slot) for slot in prefetch_slots)
    slots.extend(suffix)
    kinds.extend([pattern_supply.SOURCE_PRG] * len(suffix))
    indices.extend([-1] * len(suffix))
    return pattern_supply.count_source_runs(slots, kinds, indices)


class RunAdmission:
    """Replay tentative choices through the real allocator before accepting them.

    Selection order is quality priority; allocation order remains cell order.
    Warm choices must also be checked because protecting another resident slot
    can split an already accepted cold batch. The caller reserves room for
    mandatory prefetch and for the later WordBuf ring-end split.
    """

    def __init__(self, allocator, frame, limit, dictionary):
        self.allocator = allocator
        self.frame = frame
        self.limit = limit
        self.dictionary = dictionary
        self.choices = {}
        self._cached = None

    def commit(self, cell, key):
        self.choices[int(cell)] = key
        self._cached = None

    def fits(self, cell, key, sources, candidate_source, cold_count):
        if cold_count <= self.limit:
            return True
        signature = (cell, key, candidate_source, cold_count)
        if self._cached is not None and self._cached[0] == signature:
            return self._cached[1]
        choices = self.choices.copy()
        choices[int(cell)] = key
        updates = sorted(choices.items())
        trial = clone_allocator(self.allocator)
        placements = trial.place_frame(updates, self.frame)
        kinds = dict(sources)
        if key not in kinds:
            kinds[key] = candidate_source
        fits = count_runs(placements, [key for _, key in updates],
                          kinds, self.dictionary) <= self.limit
        self._cached = (signature, fits)
        return fits


def check_run_cap(counts, cap):
    """Reject an over-limit timed frame; untimed boot frame 0 is exempt."""
    if not cap:
        return
    for frame, count in enumerate(counts):
        if frame and int(count) > cap:
            raise ValueError(f"frame {frame}: packed runs={int(count)} exceed run_cap={cap}")
