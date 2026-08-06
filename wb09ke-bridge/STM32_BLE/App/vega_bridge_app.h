/*
 * vega_bridge_app.h — GATT client application for the Vega WB09KE bridge.
 *
 * Exposes the same public API that app_ble.c expects from the GATT client
 * layer (matching the interface that gatt_client_app.h provided in the
 * reference DataThroughput project).
 */

#ifndef VEGA_BRIDGE_APP_H
#define VEGA_BRIDGE_APP_H

#include <stdint.h>

/* ── Connection notification opcode ──────────────────────────────────────── */

typedef enum
{
    PEER_CONN_HANDLE_EVT,
    PEER_DISCON_HANDLE_EVT,
} GATT_CLIENT_APP_ConnOpcode_t;

typedef struct
{
    GATT_CLIENT_APP_ConnOpcode_t ConnOpcode;
    uint16_t ConnHdl;
} GATT_CLIENT_APP_ConnHandle_Notif_evt_t;

/* ── GATT client state ────────────────────────────────────────────────────── */

typedef enum
{
    GATT_CLIENT_APP_DISCONNECTED,
    GATT_CLIENT_APP_CONNECTED,
    GATT_CLIENT_APP_DISCOVER_SERVICES,
} GATT_CLIENT_APP_State_t;

/* ── Public API ───────────────────────────────────────────────────────────── */

/* Called once from APP_BLE_Init() */
void GATT_CLIENT_APP_Init(void);

/* Called by app_ble.c on connect/disconnect events */
void GATT_CLIENT_APP_Notification(GATT_CLIENT_APP_ConnHandle_Notif_evt_t *p_Notif);

/* Called by app_ble.c on connection_complete, schedules service discovery */
void GATT_CLIENT_APP_Discover_services(uint16_t connection_handle);

/* Called by vega_uart.c (ISR context) when a complete command frame has been
 * parsed off the UART. Copies payload into a pending-command slot and
 * schedules the relay task — must not call into the BLE stack directly, ISR
 * context can't do that. See
 * docs/interfaces/channel-selection-control-plane.md section 3.
 * len is bounded by CMD_MAX_PAYLOAD in vega_uart.c (currently 16). */
void VEGA_BRIDGE_OnCommandFrame(const uint8_t *payload, uint8_t len);

#endif /* VEGA_BRIDGE_APP_H */
