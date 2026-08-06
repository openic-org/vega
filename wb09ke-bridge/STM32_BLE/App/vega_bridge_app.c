/*
 * vega_bridge_app.c — GATT client for the Vega WB09KE BLE-to-UART bridge.
 *
 * Connects as central/client to the Kuntur STM32WB09 peripheral ("Kuntur-Headstage"),
 * discovers service 0xFFF0 and its notify characteristic 0xFFF2, enables
 * notifications, then forwards every received 244-byte StreamDataPacket_t to
 * the PC over UART using the same framing the nRF52840 bridge used:
 *
 *   [0xAA][0x55][len_lo][len_hi][payload…]
 *
 * On-connect sequence (all event-driven):
 *   connect → MTU exchange (CFG_BLE_ATT_MTU_MAX = 247)
 *           → service/char/desc discovery → enable notify on 0xFFF2 CCCD
 *   MTU exchange response → DLE(251) → symmetric DLE event → PHY 2M
 *
 * All throughput monitoring is done on the PC side (test_validator.py).
 */

#include "app_conf.h"  /* must be first — defines DT_INFO_MSG as no-op before app_ble.h can set it to printf */
#include "main.h"
#include "app_common.h"
#include "ble.h"
#include "vega_bridge_app.h"
#include "vega_uart.h"
#include "stm32_seq.h"
#include "app_ble.h"
#include "ble_evt.h"
#include <stdio.h>
#include <string.h>

/* ── Vega service / characteristic UUIDs ────────────────────────────────── */

#define VEGA_SVC_UUID      (0xFFF0)
#define VEGA_NOTIFY_UUID   (0xFFF2)
#define VEGA_CMD_UUID      (0xFFF1)   /* write-without-response, see A.2 spec */
#define VEGA_RESPONSE_UUID (0xFFF3)   /* notify, command-response, see spec section 4 */

/* ── Frame headers for UART output (bridge -> pc-app) ────────────────────── */

#define FRAME_MAGIC_0      (0xAAU)   /* sample data */
#define FRAME_MAGIC_1      (0x55U)
#define RESPONSE_MAGIC_0   (0xEEU)   /* command response, spec section 4.4 */
#define RESPONSE_MAGIC_1   (0x11U)

/* ── Bridge GATT context ─────────────────────────────────────────────────── */

typedef struct
{
    GATT_CLIENT_APP_State_t state;
    uint16_t conn_handle;

    /* Service 0xFFF0 */
    uint16_t svc_start_hdl;
    uint16_t svc_end_hdl;

    /* Characteristic 0xFFF2 */
    uint16_t notify_value_hdl;

    /* CCCD of 0xFFF2 */
    uint16_t notify_cccd_hdl;

    /* Characteristic 0xFFF1 (command write-without-response) */
    uint16_t cmd_value_hdl;

    /* Characteristic 0xFFF3 (command-response notify) */
    uint16_t resp_value_hdl;

    /* CCCD of 0xFFF3 */
    uint16_t resp_cccd_hdl;

    /* Negotiated ATT payload size */
    uint16_t mtu_payload;
} BridgeContext_t;

static BridgeContext_t s_ctx;

/* ── GATT proc-complete synchronisation (same mechanism as reference) ────── */

static void gatt_cmd_resp_release(void)
{
    UTIL_SEQ_SetEvt(1U << CFG_IDLEEVT_PROC_GATT_COMPLETE);
}

static void gatt_cmd_resp_wait(void)
{
    UTIL_SEQ_WaitEvt(1U << CFG_IDLEEVT_PROC_GATT_COMPLETE);
}


/* ── GATT parsing helpers ────────────────────────────────────────────────── */

#define UNPACK_U16(p)  ((uint16_t)(*(uint8_t *)(p)) | ((uint16_t)(*((uint8_t *)(p) + 1)) << 8))

static void parse_services(aci_att_clt_read_by_group_type_resp_event_rp0 *p_evt)
{
    if (p_evt->Connection_Handle != s_ctx.conn_handle) return;
    if (p_evt->Attribute_Data_Length != 6) return;   /* only 16-bit UUIDs */

    uint8_t  n    = p_evt->Data_Length / p_evt->Attribute_Data_Length;
    uint8_t *ptr  = p_evt->Attribute_Data_List;

    for (uint8_t i = 0; i < n; i++, ptr += 6) {
        uint16_t start = UNPACK_U16(ptr);
        uint16_t end   = UNPACK_U16(ptr + 2);
        uint16_t uuid  = UNPACK_U16(ptr + 4);

        if (uuid == VEGA_SVC_UUID) {
            s_ctx.svc_start_hdl = start;
            s_ctx.svc_end_hdl   = end;
            DT_INFO_MSG("Found 0xFFF0: handles [0x%04X-0x%04X]\r\n", start, end);
        }
    }
}

static void parse_chars(aci_att_clt_read_by_type_resp_event_rp0 *p_evt)
{
    if (p_evt->Connection_Handle != s_ctx.conn_handle) return;
    if (p_evt->Handle_Value_Pair_Length != 7) return;  /* only 16-bit UUIDs */

    uint8_t  n   = p_evt->Data_Length / p_evt->Handle_Value_Pair_Length;
    uint8_t *ptr = p_evt->Handle_Value_Pair_Data;
    p_evt->Data_Length -= 1;   /* reference pattern */

    for (uint8_t i = 0; i < n; i++, ptr += 7) {
        uint16_t value_hdl = UNPACK_U16(ptr + 3);
        uint16_t uuid      = UNPACK_U16(ptr + 5);

        if (uuid == VEGA_NOTIFY_UUID) {
            s_ctx.notify_value_hdl = value_hdl;
            DT_INFO_MSG("Found 0xFFF2 value handle: 0x%04X\r\n", value_hdl);
        } else if (uuid == VEGA_CMD_UUID) {
            s_ctx.cmd_value_hdl = value_hdl;
            DT_INFO_MSG("Found 0xFFF1 value handle: 0x%04X\r\n", value_hdl);
        } else if (uuid == VEGA_RESPONSE_UUID) {
            s_ctx.resp_value_hdl = value_hdl;
            DT_INFO_MSG("Found 0xFFF3 value handle: 0x%04X\r\n", value_hdl);
        }
    }
}

static void parse_descs(aci_att_clt_find_info_resp_event_rp0 *p_evt)
{
    if (p_evt->Connection_Handle != s_ctx.conn_handle) return;
    if (p_evt->Format != UUID_TYPE_16) return;

    uint8_t  n   = p_evt->Event_Data_Length / 4U;
    uint8_t *ptr = p_evt->Handle_UUID_Pair;

    static uint16_t cur_value_hdl = 0;

    for (uint8_t i = 0; i < n; i++, ptr += 4) {
        uint16_t handle = UNPACK_U16(ptr);
        uint16_t uuid   = UNPACK_U16(ptr + 2);

        if (uuid == CHARACTERISTIC_UUID) {
            cur_value_hdl = 0;
        } else if (uuid == CLIENT_CHAR_CONFIG_DESCRIPTOR_UUID) {
            if (cur_value_hdl == s_ctx.notify_value_hdl) {
                s_ctx.notify_cccd_hdl = handle;
                DT_INFO_MSG("Found 0xFFF2 CCCD: 0x%04X\r\n", handle);
            } else if (cur_value_hdl == s_ctx.resp_value_hdl) {
                s_ctx.resp_cccd_hdl = handle;
                DT_INFO_MSG("Found 0xFFF3 CCCD: 0x%04X\r\n", handle);
            }
        } else {
            cur_value_hdl = handle;
        }
    }
}

static void parse_notification(aci_gatt_clt_notification_event_rp0 *p_evt)
{
    if (p_evt->Attribute_Handle != s_ctx.notify_value_hdl) return;

    uint16_t      len = p_evt->Attribute_Value_Length;
    const uint8_t hdr[4] = {
        FRAME_MAGIC_0,
        FRAME_MAGIC_1,
        (uint8_t)(len & 0xFFU),
        (uint8_t)(len >> 8),
    };

    VEGA_UART_Write(hdr, 4U);
    VEGA_UART_Write(p_evt->Attribute_Value, len);
}

/* Relays a 0xFFF3 SET_CHANNELS readback notification to the pc-app — see
 * docs/interfaces/channel-selection-control-plane.md section 4.4. Same
 * framing shape as parse_notification()'s data frame, distinct magic. */
static void parse_response_notification(aci_gatt_clt_notification_event_rp0 *p_evt)
{
    if (p_evt->Attribute_Handle != s_ctx.resp_value_hdl) return;

    uint16_t      len = p_evt->Attribute_Value_Length;
    const uint8_t hdr[4] = {
        RESPONSE_MAGIC_0,
        RESPONSE_MAGIC_1,
        (uint8_t)(len & 0xFFU),
        (uint8_t)(len >> 8),
    };

    VEGA_UART_Write(hdr, 4U);
    VEGA_UART_Write(p_evt->Attribute_Value, len);
}

/* ── GATT event handler ──────────────────────────────────────────────────── */

static BLEEVT_EvtAckStatus_t Bridge_EventHandler(aci_blecore_event *p_evt)
{
    switch (p_evt->ecode)
    {
    case ACI_ATT_CLT_READ_BY_GROUP_TYPE_RESP_VSEVT_CODE:
        parse_services((aci_att_clt_read_by_group_type_resp_event_rp0 *)p_evt->data);
        break;

    case ACI_ATT_CLT_READ_BY_TYPE_RESP_VSEVT_CODE:
        parse_chars((aci_att_clt_read_by_type_resp_event_rp0 *)p_evt->data);
        break;

    case ACI_ATT_CLT_FIND_INFO_RESP_VSEVT_CODE:
        parse_descs((aci_att_clt_find_info_resp_event_rp0 *)p_evt->data);
        break;

    case ACI_GATT_CLT_NOTIFICATION_VSEVT_CODE:
        parse_notification((aci_gatt_clt_notification_event_rp0 *)p_evt->data);
        parse_response_notification((aci_gatt_clt_notification_event_rp0 *)p_evt->data);
        break;

    case ACI_GATT_CLT_PROC_COMPLETE_VSEVT_CODE:
        gatt_cmd_resp_release();
        break;

    case ACI_ATT_EXCHANGE_MTU_RESP_VSEVT_CODE: {
        aci_att_exchange_mtu_resp_event_rp0 *mtu =
            (aci_att_exchange_mtu_resp_event_rp0 *)p_evt->data;
        s_ctx.mtu_payload = (mtu->MTU < 247U) ? (mtu->MTU - 3U) : 244U;
        DT_INFO_MSG("MTU exchanged: %u  payload %u\r\n", mtu->MTU, s_ctx.mtu_payload);
        /* Trigger DLE now that MTU is known. */
        tBleStatus st = hci_le_set_data_length_api(s_ctx.conn_handle, 251, 2120);
        if (st != BLE_STATUS_SUCCESS)
            DT_INFO_MSG("DLE cmd failed: 0x%02X\r\n", st);
        else
            DT_INFO_MSG("DLE cmd OK\r\n");
        break;
    }

    case ACI_GATT_CLT_INDICATION_VSEVT_CODE: {
        aci_gatt_clt_indication_event_rp0 *ind =
            (aci_gatt_clt_indication_event_rp0 *)p_evt->data;
        aci_gatt_clt_confirm_indication(ind->Connection_Handle,
                                        BLE_GATT_UNENHANCED_ATT_L2CAP_CID);
        break;
    }

    default:
        break;
    }

    return BLEEVT_NoAck;
}

/* ── Discovery task ──────────────────────────────────────────────────────── */

static void vega_bridge_discover_all(void)
{
    if (s_ctx.state != GATT_CLIENT_APP_DISCOVER_SERVICES) return;

    uint16_t conn = s_ctx.conn_handle;
    tBleStatus ret;

    /* MTU exchange — must complete before service discovery (0x88 if concurrent) */
    ret = aci_gatt_clt_exchange_config(conn);
    if (ret == BLE_STATUS_SUCCESS) gatt_cmd_resp_wait();

    /* 1. Discover all primary services */
    ret = aci_gatt_clt_disc_all_primary_services(conn, BLE_GATT_UNENHANCED_ATT_L2CAP_CID);
    if (ret == BLE_STATUS_SUCCESS) gatt_cmd_resp_wait();

    /* 2. Discover all characteristics */
    ret = aci_gatt_clt_disc_all_char_of_service(conn,
                                                 BLE_GATT_UNENHANCED_ATT_L2CAP_CID,
                                                 s_ctx.svc_start_hdl,
                                                 s_ctx.svc_end_hdl);
    if (ret == BLE_STATUS_SUCCESS) gatt_cmd_resp_wait();

    /* 3. Discover all descriptors */
    ret = aci_gatt_clt_disc_all_char_desc(conn,
                                           BLE_GATT_UNENHANCED_ATT_L2CAP_CID,
                                           s_ctx.svc_start_hdl,
                                           s_ctx.svc_end_hdl);
    if (ret == BLE_STATUS_SUCCESS) gatt_cmd_resp_wait();

    /* 4. Enable notifications */
    if (s_ctx.notify_cccd_hdl != 0x0000U) {
        uint16_t enable = 0x0001U;
        ret = aci_gatt_clt_write(conn,
                                  BLE_GATT_UNENHANCED_ATT_L2CAP_CID,
                                  s_ctx.notify_cccd_hdl,
                                  2,
                                  (uint8_t *)&enable);
        if (ret == BLE_STATUS_SUCCESS) {
            gatt_cmd_resp_wait();
            DT_INFO_MSG("0xFFF2 notify enabled — streaming\r\n");
        }
    } else {
        DT_INFO_MSG("ERROR: CCCD not found — check service UUIDs\r\n");
    }

    /* 5. Enable notifications on the command-response characteristic — see
     * docs/interfaces/channel-selection-control-plane.md section 4.4. Not
     * fatal if missing (older headstage firmware pre-dating this feature) —
     * SET_CHANNELS still works, readback confirmation just won't arrive. */
    if (s_ctx.resp_cccd_hdl != 0x0000U) {
        uint16_t enable = 0x0001U;
        ret = aci_gatt_clt_write(conn,
                                  BLE_GATT_UNENHANCED_ATT_L2CAP_CID,
                                  s_ctx.resp_cccd_hdl,
                                  2,
                                  (uint8_t *)&enable);
        if (ret == BLE_STATUS_SUCCESS) {
            gatt_cmd_resp_wait();
            DT_INFO_MSG("0xFFF3 notify enabled\r\n");
        }
    } else {
        DT_INFO_MSG("0xFFF3 CCCD not found — readback confirmation unavailable\r\n");
    }

    s_ctx.state = GATT_CLIENT_APP_CONNECTED;

    /* Check for a second connection that arrived while we were busy */
    UTIL_SEQ_SetTask(1U << CFG_TASK_DISCOVER_SERVICES_ID, CFG_SEQ_PRIO_0);
}

/* ── UART command relay task ─────────────────────────────────────────────── */

/* Single pending-command slot, not a queue: if a second frame arrives before
 * the sequencer task drains the first, it overwrites s_cmd_relay_buf and the
 * first command is lost (last-write-wins). Acceptable for V1's infrequent,
 * user-triggered SET_CHANNELS — no torn reads, since the M0+ ISR always runs
 * to completion before the task it interrupted resumes. Revisit if a command
 * is added that can't tolerate coalescing/loss under back-to-back writes. */
static uint8_t s_cmd_relay_buf[VEGA_UART_CMD_MAX_PAYLOAD];
static uint8_t s_cmd_relay_len;

void VEGA_BRIDGE_OnCommandFrame(const uint8_t *payload, uint8_t len)
{
    /* ISR context — copy and defer, never touch the BLE stack here. len is
     * already bounded by vega_uart.c's own VEGA_UART_CMD_MAX_PAYLOAD check. */
    memcpy(s_cmd_relay_buf, payload, len);
    s_cmd_relay_len = len;
    UTIL_SEQ_SetTask(1U << CFG_TASK_UART_CMD_RELAY_ID, CFG_SEQ_PRIO_0);
}

/* Transparent relay — no interpretation of the payload beyond framing, see
 * docs/interfaces/channel-selection-control-plane.md section 3. A frame that
 * arrives while disconnected or before 0xFFF1 is discovered is dropped;
 * there's no response channel to report that back to the pc-app on a
 * write-without-response characteristic. */
static void vega_bridge_relay_command(void)
{
    if (s_ctx.state != GATT_CLIENT_APP_CONNECTED || s_ctx.cmd_value_hdl == 0x0000U) {
        DT_INFO_MSG("cmd relay: not ready (state=%d, hdl=0x%04X), dropped\r\n",
                     s_ctx.state, s_ctx.cmd_value_hdl);
        return;
    }

    tBleStatus ret = aci_gatt_clt_write_without_resp(s_ctx.conn_handle,
                                                      BLE_GATT_UNENHANCED_ATT_L2CAP_CID,
                                                      s_ctx.cmd_value_hdl,
                                                      s_cmd_relay_len,
                                                      s_cmd_relay_buf);
    if (ret != BLE_STATUS_SUCCESS)
        DT_INFO_MSG("cmd relay: aci_gatt_clt_write_without_resp failed 0x%02X\r\n", ret);
    else
        DT_INFO_MSG("cmd relay: wrote %u byte(s) to hdl 0x%04X (cmd=0x%02X)\r\n",
                     s_cmd_relay_len, s_ctx.cmd_value_hdl, s_cmd_relay_buf[0]);
}

/* ── Public API ──────────────────────────────────────────────────────────── */

void GATT_CLIENT_APP_Init(void)
{
    memset(&s_ctx, 0, sizeof(s_ctx));
    s_ctx.conn_handle = 0xFFFFU;
    s_ctx.state       = GATT_CLIENT_APP_DISCONNECTED;
    s_ctx.mtu_payload = 20U;   /* default ATT_MTU(23) - 3 */

    int ret = BLEEVT_RegisterGattEvtHandler(Bridge_EventHandler);
    if (ret != 0) Error_Handler();

    UTIL_SEQ_RegTask(1U << CFG_TASK_DISCOVER_SERVICES_ID, UTIL_SEQ_RFU,
                     vega_bridge_discover_all);
    UTIL_SEQ_RegTask(1U << CFG_TASK_UART_CMD_RELAY_ID, UTIL_SEQ_RFU,
                     vega_bridge_relay_command);

    DT_INFO_MSG("Vega bridge GATT client ready\r\n");
}

void GATT_CLIENT_APP_Notification(GATT_CLIENT_APP_ConnHandle_Notif_evt_t *p_Notif)
{
    switch (p_Notif->ConnOpcode)
    {
    case PEER_CONN_HANDLE_EVT:
        s_ctx.conn_handle = p_Notif->ConnHdl;
        s_ctx.state       = GATT_CLIENT_APP_CONNECTED;
        DT_INFO_MSG("BLE: connected to headstage, handle 0x%04X\r\n", s_ctx.conn_handle);
        break;

    case PEER_DISCON_HANDLE_EVT:
        DT_INFO_MSG("BLE: DISCONNECTED from headstage (was handle 0x%04X, state=%d)\r\n",
                     s_ctx.conn_handle, s_ctx.state);
        memset(&s_ctx, 0, sizeof(s_ctx));
        s_ctx.conn_handle = 0xFFFFU;
        s_ctx.state       = GATT_CLIENT_APP_DISCONNECTED;
        s_ctx.mtu_payload = 20U;
        break;

    default:
        break;
    }
}

void GATT_CLIENT_APP_Discover_services(uint16_t connection_handle)
{
    if (s_ctx.conn_handle == connection_handle &&
        s_ctx.state == GATT_CLIENT_APP_CONNECTED) {
        s_ctx.state = GATT_CLIENT_APP_DISCOVER_SERVICES;
        UTIL_SEQ_SetTask(1U << CFG_TASK_DISCOVER_SERVICES_ID, CFG_SEQ_PRIO_0);
    }
}
