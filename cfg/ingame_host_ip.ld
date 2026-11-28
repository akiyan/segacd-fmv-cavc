OUTPUT_ARCH(m68k)

/* In-game player test host: the BIOS loads this IP at 0xFF0000. It copies
   the embedded Main module to INGAME_MAIN_BASE, so its own image and state
   must stay below that address. */
SECTIONS
{
  .text 0xFF0000 :
  {
    *(.text)
  }

  .bss (NOLOAD) :
  {
    . = ALIGN(2);
    *(.bss)
  }

  ASSERT(. <= INGAME_MAIN_BASE, "test host IP overlaps the in-game Main module")
}
