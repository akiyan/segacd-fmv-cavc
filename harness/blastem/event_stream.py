"""Read VDP writes and scanout boundaries from the BlastEm BLSTEL v2 log."""

from dataclasses import dataclass
import struct
import zlib


MAGIC = b"BLSTEL\x02\x00"
PAYLOAD_SIZES = (0, 4, 1, 3, 2, 3, 2, 1, 1, 5, 3, 3)
CHUNK_BYTES = 256 * 1024
HUD_ADDRESS = 0xF000
HUD_WORDS = 40
HUD_FONT = 1744
MULTIPART_SIGNATURE = b"MPRT"


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    cycle: int
    address: int
    data: bytes


@dataclass(frozen=True, slots=True)
class Publication:
    capture_index: int
    cycle: int
    frame: int
    hud: tuple[int, ...]
    vram: bytes
    cram: bytes
    vsram: bytes
    registers: bytes
    dispatcher: tuple[int, int, int] | None


class _Inflater:
    def __init__(self, source):
        self.source = source
        self.decoder = zlib.decompressobj()
        self.data = b""
        self.position = 0

    def get(self, size, *, allow_eof=False):
        while len(self.data) - self.position < size:
            if self.decoder.eof:
                if self.decoder.unused_data or self.source.read(1):
                    raise ValueError("trailing data after BLSTEL compressed stream")
                if allow_eof and self.position == len(self.data):
                    return b""
                raise ValueError("truncated BLSTEL event")
            compressed = self.decoder.unconsumed_tail or self.source.read(CHUNK_BYTES)
            if not compressed:
                raise ValueError("incomplete BLSTEL compressed stream")
            self.data = self.data[self.position:] + self.decoder.decompress(compressed, CHUNK_BYTES)
            self.position = 0
        start = self.position
        self.position += size
        return self.data[start:self.position]


def iter_events(path):
    """Yield normalized VDP writes and FRAME flushes, in recorded order.

    Timestamps are unwrapped master-clock cycles. VRAM/CRAM/VSRAM offsets
    address bytes, register offsets address registers. CRAM/VSRAM words are
    big-endian Genesis bus values. FRAME carries no data. BLSTEL identifies
    writes but carries neither the writer's CPU PC nor the DMA command.
    """
    with open(path, "rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise ValueError("expected a BlastEm BLSTEL v2 file")
        identity = source.read(3)
        if len(identity) != 3 or len(source.read(identity[2])) != identity[2]:
            raise ValueError("truncated BLSTEL system header")
        try:
            yield from _events(_Inflater(source))
        except zlib.error as exc:
            raise ValueError(f"invalid BLSTEL compressed stream: {exc}") from exc


def _events(stream):
    cycle = byte_address = word_address = autoincrement = mode = 0
    while first := stream.get(1, allow_eof=True):
        header = first[0]
        count = 1
        if header >> 4 == 13:
            count = (header & 15) + 2
            header = stream.get(1)[0]
        form = header >> 4
        if form < 14:
            kind, delta = form, (header & 15) + 16
        else:
            kind = header & 15
            delta = int.from_bytes(stream.get(form - 12), "big", signed=form == 15)
        if kind >= len(PAYLOAD_SIZES) or (count > 1 and kind in (0, 1)):
            raise ValueError(f"unsupported BLSTEL file event {kind}")
        size = PAYLOAD_SIZES[kind]
        # ADJUST subtracts from both the writer's and machine's local clocks;
        # subsequent deltas already use the adjusted origin. Accumulating the
        # deltas directly keeps one clock even after the hardware wraps.
        for _ in range(count):
            payload = stream.get(size) if size else b""
            cycle += delta
            if kind == 0:
                yield Event("FRAME", cycle, 0, b"")
            elif kind == 4:
                address, value = payload
                if address == 1:
                    mode = value
                elif address == 15:
                    autoincrement = value
                yield Event("REGISTER", cycle, address, payload[1:])
            elif 5 <= kind <= 8:
                if kind == 5:
                    byte_address = (payload[0] << 8) | payload[1]
                elif kind == 6:
                    byte_address += payload[0]
                elif kind == 7:
                    byte_address += 1
                else:
                    byte_address += autoincrement
                byte_address &= 0xFFFF
                address = byte_address ^ 1
                if not mode & 4:
                    address = ((address & 0x3DFD) | ((address << 8) & 0x200)
                               | ((address >> 8) & 2))
                yield Event("VRAM", cycle, address, payload[-1:])
            elif kind in (9, 10):
                if kind == 9:
                    word_address = int.from_bytes(payload[:3], "big")
                else:
                    word_address += payload[0]
                # In 128 KiB mode the current fork maps this word write to a
                # single byte in its physical 64 KiB VDP memory.
                address = ((word_address & 0x3FC) | ((word_address >> 1) & 0xFC01)
                           | ((word_address >> 9) & 2)) ^ 1
                yield Event("VRAM", cycle, address, payload[-1:])
            elif kind == 11:
                address = payload[0]
                if address >= 128:
                    yield Event("VSRAM", cycle, (address & 63) * 2, payload[1:])
                elif mode & 4:
                    yield Event("CRAM", cycle, address & 0x7E, payload[1:])
                else:
                    value = int.from_bytes(payload[1:], "big")
                    color = ((value << 1) & 0xE) | ((value << 2) & 0xE0) | (value & 0xE00)
                    yield Event("CRAM", cycle, (address & 31) * 2, color.to_bytes(2, "big"))


def rgb333(word):
    """Convert a Genesis CRAM word to packed red, green, blue 3-bit fields."""
    return ((word & 0xE) >> 1) | ((word & 0xE0) >> 2) | ((word & 0xE00) >> 3)


def iter_publications(path):
    """Read CAVC DEBUG publications from a BlastEm event log."""
    yield from publications(iter_events(path))


def publications(events):
    """Yield CAVC DEBUG publications with final VDP state at their scanout.

    A fresh complete 40-word HUD write identifies a publication, including
    player-only FFFF/FFFE markers. Repeated scanouts do not create publications.
    The optional dispatcher identifies the latest complete multipart marker
    (zero-based part, cycle, one-based visit) before this publication.
    """
    vram = bytearray(0x10000)
    cram = bytearray(128)
    vsram = bytearray(128)
    registers = bytearray(256)
    memory = {"VRAM": vram, "CRAM": cram, "VSRAM": vsram, "REGISTER": registers}
    hud_bytes = set()
    marker_bytes = set()
    pending = dispatcher = None
    capture = 0
    for event in events:
        if event.kind == "FRAME":
            if pending is not None:
                frame, digits, cycle = pending
                yield Publication(capture, cycle, frame, digits, bytes(vram),
                                  bytes(cram), bytes(vsram), bytes(registers), dispatcher)
                pending = None
            capture += 1
            continue
        memory[event.kind][event.address:event.address + len(event.data)] = event.data
        if event.kind != "VRAM":
            continue
        if event.address < 16:
            if event.address == 1:
                marker_bytes.clear()
            marker_bytes.add(event.address)
            if len(marker_bytes) == 16:
                marker_bytes.clear()
                if vram[:4] == MULTIPART_SIGNATURE and vram[14:16] == b"EN":
                    dispatcher = struct.unpack_from(">HII", vram, 4)
        if HUD_ADDRESS <= event.address < HUD_ADDRESS + HUD_WORDS * 2:
            if event.address == HUD_ADDRESS + 1:
                hud_bytes.clear()
            hud_bytes.add(event.address)
            if len(hud_bytes) != HUD_WORDS * 2:
                continue
            hud_bytes.clear()
            tiles = tuple(word & 0x7FF for word in struct.unpack_from(">40H", vram, HUD_ADDRESS))
            if all(HUD_FONT <= tile < HUD_FONT + 16 for tile in tiles):
                if pending is not None:
                    raise ValueError(f"two CAVC publications in BlastEm scanout {capture}")
                digits = tuple(tile - HUD_FONT for tile in tiles)
                frame = 0
                for digit in digits[:4]:
                    frame = (frame << 4) | digit
                pending = frame, digits, event.cycle
