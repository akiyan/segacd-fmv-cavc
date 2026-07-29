OUTPUT_ARCH(m68k)

SECTIONS
{
  .text 0x006000 :
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

  ASSERT(. <= 0x007400, "resident Sub image exceeds its initial PRG allocation")
}
