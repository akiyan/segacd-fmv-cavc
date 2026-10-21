OUTPUT_ARCH(m68k)

SECTIONS
{
  /* The loader launcher executes from the Sub-owned Word-RAM bank. */
  .text 0x0DE000 :
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

  ASSERT(. <= 0x0E0000, "Word-RAM loader launcher exceeds 8 KiB")
}
