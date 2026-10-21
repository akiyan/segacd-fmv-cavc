"""Time production adapter calls without replacing encoder calculations."""

import time
import stages
import pack_validation

measurements = {"encode_seconds": 0.0, "pack_seconds": 0.0}
original_stages = stages.install
original_pack = pack_validation.install


def timed(function, key):
    def call(*args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            measurements[key] += time.perf_counter() - started
    return call


def install_stages(sim, *args, **kwargs):
    original_stages(sim, *args, **kwargs)
    sim.main = timed(sim.main, "encode_seconds")


def install_pack(pack):
    original_pack(pack)
    pack.main = timed(pack.main, "pack_seconds")


stages.install = install_stages
pack_validation.install = install_pack
