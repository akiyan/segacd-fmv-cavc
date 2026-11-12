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

  ASSERT(. <= 0xFF2200, "Main IP permanent text/data overlaps transient codegen area")

  /* Boot-only routines and preload tables occupy the generated-code region
     until Main copies their persistent data and initializes its handlers. */
  .startup 0xFF2200 :
  {
    *(.startup)
    . = ALIGN(0x10);
  }

  ASSERT(. <= 0xFF4B00, "startup section exceeds generated-code area")

  /* Runtime state (M-STATE) sits in its fixed 8.25 KiB reservation right
     after the generated-handler range (M-CODE ends at 0xFF6700).
     The reservation covers the worst-case DEBUG/H40 build. */
  .bss 0xFF6700 (NOLOAD) :
  {
    *(.bss)
  }

  ASSERT(. <= 0xFF8800, "Main IP runtime state overflows the fixed 8.25 KiB M-STATE reservation")
}
