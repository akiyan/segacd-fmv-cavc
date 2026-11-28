OUTPUT_ARCH(m68k)

/* In-game Main module: loaded by the host at INGAME_MAIN_BASE. The image
   and its state together stay within the 16 KiB Main-RAM budget. */
SECTIONS
{
  .text INGAME_MAIN_BASE :
  {
    *(.text)
  }

  .bss (NOLOAD) :
  {
    *(.bss)
  }

  ASSERT(. - INGAME_MAIN_BASE <= 0x4000, "in-game Main module exceeds 16 KiB")
}
