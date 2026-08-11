/* Host-test stub for app_common.h — fpga_spi.c only needs APP_DBG_MSG. */
#ifndef HOST_APP_COMMON_H
#define HOST_APP_COMMON_H

#include <stdio.h>

extern int dbg_quiet;
#define APP_DBG_MSG(...)  do { if (!dbg_quiet) printf(__VA_ARGS__); } while (0)

#endif /* HOST_APP_COMMON_H */
