/*
 * Disc-header fields that differ between release regions (Japan).
 *
 * SECURITY_REGION selects this file, and the build copies it next to the
 * matching sec_<region>.bin security code as disc_region.inc.  Both pieces
 * belong to the same region: the security code is what a console validates,
 * and these fields are what it and every tool read the disc as.
 *
 * Each field is a macro because the two positions are far apart in the
 * header: the hardware type sits at 0x100 and the region support field at
 * 0x1F0.  A macro lets one include serve both without splitting the file.
 * Each one must emit exactly 16 bytes.
 */

	.macro disc_hardware_type
	.ascii "SEGA MEGA DRIVE "
	.endm

	.macro disc_region_support
	.ascii "J               "
	.endm

/*
 * Where the Main IP's own code starts inside the IP image.  The BIOS enters
 * the IP at its first byte, which is this region's security code, and that
 * code falls through to a branch placed right after it.  The branch target is
 * padded to this offset, so it has to clear the 342-byte Japanese security
 * code plus that 4-byte branch.
 */
	.set DISC_IP_ENTRY_OFFSET, 0x584
