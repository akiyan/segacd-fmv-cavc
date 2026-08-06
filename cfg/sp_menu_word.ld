OUTPUT_ARCH(m68k)

SECTIONS
{
  /* The menu launcher executes from the Sub-owned Word-RAM bank. */
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

  ASSERT(. <= 0x0DF400, "Word-RAM menu launcher exceeds 5 KiB")
}
