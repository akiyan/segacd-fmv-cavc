OUTPUT_ARCH(m68k)

SECTIONS
{
  .text 0x076800 :
  {
    *(.text)
  }

  .data :
  {
    . = ALIGN(4);
    *(.data)
  }

  ASSERT(. <= 0x076DA0, "Sub extension exceeds ADPCM preload padding")
}
