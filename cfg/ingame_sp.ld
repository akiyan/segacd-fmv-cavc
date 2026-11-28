OUTPUT_ARCH(m68k)

/* In-game Sub module: loaded by the host Sub program at 0x40000. Its code
   and state end below the ADPCM tables, which sit directly under PrgBuf. */
SECTIONS
{
  .text 0x040000 :
  {
    *(.text)
  }

  .data :
  {
    . = ALIGN(0x10);
    *(.data)
  }

  .bss :
  {
    *(.bss)
  }

  ASSERT(. <= ingame_image_limit, "in-game Sub module overlaps its ADPCM tables")
}
