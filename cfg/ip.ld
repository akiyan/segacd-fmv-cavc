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

  ASSERT(. <= 0xFF2100, "Main IP permanent text/data overlaps transient codegen area")

  /* Keep the former startup-asset region as an explicit boundary for the
     generated Main-CPU code area. The minimal preload counter now reuses the
     permanent hexadecimal HUD font, so this section is normally empty. */
  .startup 0xFF2100 :
  {
    *(.startup)
    . = ALIGN(0x10);
  }

  ASSERT(. <= 0xFF4A00, "startup section exceeds generated-code area")

  /* Runtime state (M-STATE) sits in its fixed 8.25 KiB reservation right
     after the generated handler/blitter range (M-CODE ends at 0xFF6700).
     The reservation covers the worst-case DEBUG/H40 build. */
  .bss 0xFF6700 (NOLOAD) :
  {
    *(.bss)
  }

  ASSERT(. <= 0xFF8800, "Main IP runtime state overflows the fixed 8.25 KiB M-STATE reservation")
}
