OUTPUT_ARCH(m68k)

SECTIONS
{
  .text 0xFF0000 :
  {
    *(.text)
  }

  .data :
  {
    . = ALIGN(0x10);
    *(.data)
  }

  /* Keep the menu image below the same Main-RAM state boundary used by the
     movie player.  The ISO builder also pads the image to its fixed 20 KiB
     Word-RAM slot, so a larger menu fails before it can make a disc. */
  ASSERT(. <= 0xFF6700, "multi-video menu image overlaps Main-RAM state")

  .bss 0xFF6700 (NOLOAD) :
  {
    *(.bss)
  }

  ASSERT(. <= 0xFF8800, "multi-video menu state overflows Main-RAM state")
}
