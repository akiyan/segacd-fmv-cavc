#ifndef SEGACD_GPGX_LOGVDP_ERROR_DECL_H
#define SEGACD_GPGX_LOGVDP_ERROR_DECL_H

/*
 * LOGVDP calls the frontend's existing error() logger from vdp_ctrl.c, but the
 * pinned source does not expose its declaration through a shared header.
 * Force-include this declaration at build time so current C compilers do not
 * reject the otherwise unchanged upstream source.
 */
void error(char *format, ...);

#endif
