/*
 * app_ble.c — BLE GAP/GATT central for the Vega WB09KE bridge.
 *
 * Scans for the advertisement name "Kuntur-Headstage", connects, and hands off to
 * vega_bridge_app.c for GATT discovery and notification forwarding.
 *
 * On-connect LL parameter sequence (strictly sequential, event-triggered):
 *   connect (CI=7.5 ms, initial) → MTU exchange (in vega_bridge_app.c)
 *   MTU response → DLE(251) → HCI_LE_DATA_LENGTH_CHANGE symmetric
 *               → PHY 2M (CFG_TASK_PHY_UPDATE_ID)
 *
 * Based on STM32Cube_FW_WB0_V1.4.x BLE_DataThroughput_Client example with
 * DT-specific scan filter, CRC, TX, and button code removed.
 */

/* Include our app_conf.h first so its include guard blocks the reference copy
 * that would otherwise be found via main.h → app_common.h → app_conf.h (GCC
 * searches the including file's directory before the -I flags). */
#include "app_conf.h"

#include <stdio.h>
#include <string.h>
#include "main.h"
#include "stm32wb0x.h"
#include "ble.h"
#include "gatt_profile.h"
#include "gap_profile.h"
#include "app_ble.h"
#include "stm32wb0x_hal_radio_timer.h"
#include "bleplat.h"
#include "nvm_db.h"
#include "blenvm.h"
#include "pka_manager.h"
#include "stm32_seq.h"
#include "vega_bridge_app.h"

/* ── Private types ─────────────────────────────────────────────────────────── */

typedef struct
{
    uint8_t  ioCapability;
    uint8_t  mitm_mode;
    uint8_t  bonding_mode;
    uint8_t  encryptionKeySizeMin;
    uint8_t  encryptionKeySizeMax;
    uint8_t  initiateSecurity;
} SecurityParams_t;

typedef struct
{
    SecurityParams_t bleSecurityParam;
    uint16_t         gapServiceHandle;
    uint16_t         devNameCharHandle;
    uint16_t         appearanceCharHandle;
    uint16_t         connectionHandle;
} BleGlobalContext_t;

typedef struct
{
    BleGlobalContext_t BleApplicationContext_legacy;
    APP_BLE_ConnStatus_t Device_Connection_Status;
    uint8_t deviceServerFound;
    uint8_t deviceServerBdAddrType;
    uint8_t a_deviceServerBdAddr[BD_ADDR_SIZE];
} BleApplicationContext_t;

/* ── Private variables ─────────────────────────────────────────────────────── */

NO_INIT(uint32_t dyn_alloc_a[BLE_DYN_ALLOC_SIZE >> 2]);

static BleApplicationContext_t bleAppContext;
GATT_CLIENT_APP_ConnHandle_Notif_evt_t clientHandleNotification;

static const char a_GapDeviceName[] = { 'V','e','g','a',' ','B','r','i','d','g','e' };

/* ── Forward declarations ──────────────────────────────────────────────────── */

static void connection_complete_event(uint8_t Status, uint16_t Connection_Handle,
                                      uint8_t Role,
                                      uint8_t Peer_Address_Type, uint8_t Peer_Address[6],
                                      uint16_t Connection_Interval,
                                      uint16_t Peripheral_Latency,
                                      uint16_t Supervision_Timeout);
static void gap_cmd_resp_wait(void);
static void gap_cmd_resp_release(void);
static uint8_t analyse_adv_report(uint8_t adv_data_size, uint8_t *p_adv_data,
                                   uint8_t address_type, uint8_t *p_address);
static void Connect_Request(void);
static void Scan_Request(void);
static void Connection_Update(void);
static void PHY_Update_Task(void);

/* ── Module init ───────────────────────────────────────────────────────────── */

void ModulesInit(void)
{
    BLENVM_Init();
    if (PKAMGR_Init() == PKAMGR_ERROR) Error_Handler();
}

void BLE_Init(void)
{
    uint8_t  role  = GAP_CENTRAL_ROLE;
    tBleStatus ret;
    uint16_t gatt_service_changed_handle;
    uint16_t gap_dev_name_char_handle;
    uint16_t gap_appearance_char_handle;
    uint16_t gap_periph_pref_conn_param_char_handle;
    uint8_t  bd_address[6] = {0};
    uint8_t  bd_address_len = 6;
    uint16_t appearance = CFG_GAP_APPEARANCE;

    BLE_STACK_InitTypeDef BLE_STACK_InitParams = {
        .BLEStartRamAddress  = (uint8_t *)dyn_alloc_a,
        .TotalBufferSize     = BLE_DYN_ALLOC_SIZE,
        .NumAttrRecords      = CFG_BLE_NUM_GATT_ATTRIBUTES,
        .MaxNumOfClientProcs = CFG_BLE_NUM_OF_CONCURRENT_GATT_CLIENT_PROC,
        .NumOfRadioTasks     = CFG_BLE_NUM_RADIO_TASKS,
        .NumOfEATTChannels   = CFG_BLE_NUM_EATT_CHANNELS,
        .NumBlockCount       = CFG_BLE_MBLOCKS_COUNT,
        .ATT_MTU             = CFG_BLE_ATT_MTU_MAX,
        .MaxConnEventLength  = CFG_BLE_CONN_EVENT_LENGTH_MAX,
        .SleepClockAccuracy  = CFG_BLE_SLEEP_CLOCK_ACCURACY,
        .NumOfAdvDataSet     = CFG_BLE_NUM_ADV_SETS,
        .NumOfSubeventsPAwR  = CFG_BLE_NUM_PAWR_SUBEVENTS,
        .MaxPAwRSubeventDataCount = CFG_BLE_PAWR_SUBEVENT_DATA_COUNT_MAX,
        .NumOfAuxScanSlots   = CFG_BLE_NUM_AUX_SCAN_SLOTS,
        .FilterAcceptListSizeLog2 = CFG_BLE_FILTER_ACCEPT_LIST_SIZE_LOG2,
        .L2CAP_MPS           = CFG_BLE_COC_MPS_MAX,
        .L2CAP_NumChannels   = CFG_BLE_COC_NBR_MAX,
        .NumOfSyncSlots      = CFG_BLE_NUM_SYNC_SLOTS,
        .CTE_MaxNumAntennaIDs  = CFG_BLE_NUM_CTE_ANTENNA_IDS_MAX,
        .CTE_MaxNumIQSamples   = CFG_BLE_NUM_CTE_IQ_SAMPLES_MAX,
        .NumOfSyncBIG        = CFG_BLE_NUM_SYNC_BIG_MAX,
        .NumOfBrcBIG         = CFG_BLE_NUM_BRC_BIG_MAX,
        .NumOfSyncBIS        = CFG_BLE_NUM_SYNC_BIS_MAX,
        .NumOfBrcBIS         = CFG_BLE_NUM_BRC_BIS_MAX,
        .NumOfCIG            = CFG_BLE_NUM_CIG_MAX,
        .NumOfCIS            = CFG_BLE_NUM_CIS_MAX,
        .ExtraLLProcedureContexts = CFG_BLE_EXTRA_LL_PROCEDURE_CONTEXTS,
        .isr0_fifo_size      = CFG_BLE_ISR0_FIFO_SIZE,
        .isr1_fifo_size      = CFG_BLE_ISR1_FIFO_SIZE,
        .user_fifo_size      = CFG_BLE_USER_FIFO_SIZE,
    };

    ret = BLE_STACK_Init(&BLE_STACK_InitParams);
    if (ret != BLE_STATUS_SUCCESS) Error_Handler();

    ret = aci_hal_set_tx_power_level(0, CFG_TX_POWER);
    (void)ret;

    ret = aci_gatt_srv_profile_init(GATT_INIT_SERVICE_CHANGED_BIT,
                                     &gatt_service_changed_handle);
    (void)ret;

    ret = aci_gap_init(0U, CFG_BD_ADDRESS_TYPE);
    (void)ret;

    ret = aci_gap_profile_init(role, 0U,
                               &gap_dev_name_char_handle,
                               &gap_appearance_char_handle,
                               &gap_periph_pref_conn_param_char_handle);
    (void)ret;

#if (CFG_BD_ADDRESS_TYPE == HCI_ADDR_STATIC_RANDOM_ADDR)
    aci_hal_read_config_data(CONFIG_DATA_STORED_STATIC_RANDOM_ADDRESS,
                             &bd_address_len, bd_address);
    DT_INFO_MSG("BLE addr: %02x:%02x:%02x:%02x:%02x:%02x\r\n",
                bd_address[5], bd_address[4], bd_address[3],
                bd_address[2], bd_address[1], bd_address[0]);
#else
    (void)bd_address;
    (void)bd_address_len;
#endif

    Gap_profile_set_dev_name(0, sizeof(a_GapDeviceName), (uint8_t *)a_GapDeviceName);
    Gap_profile_set_appearance(0, sizeof(appearance), (uint8_t *)&appearance);

    bleAppContext.BleApplicationContext_legacy.bleSecurityParam.ioCapability   = CFG_IO_CAPABILITY;
    bleAppContext.BleApplicationContext_legacy.bleSecurityParam.mitm_mode      = CFG_MITM_PROTECTION;
    bleAppContext.BleApplicationContext_legacy.bleSecurityParam.bonding_mode   = CFG_BONDING_MODE;
    bleAppContext.BleApplicationContext_legacy.bleSecurityParam.encryptionKeySizeMin = CFG_ENCRYPTION_KEY_SIZE_MIN;
    bleAppContext.BleApplicationContext_legacy.bleSecurityParam.encryptionKeySizeMax = CFG_ENCRYPTION_KEY_SIZE_MAX;

    aci_gap_set_io_capability(bleAppContext.BleApplicationContext_legacy.bleSecurityParam.ioCapability);
    aci_gap_set_security_requirements(bleAppContext.BleApplicationContext_legacy.bleSecurityParam.bonding_mode,
                                       bleAppContext.BleApplicationContext_legacy.bleSecurityParam.mitm_mode,
                                       CFG_SC_SUPPORT,
                                       CFG_KEYPRESS_NOTIFICATION_SUPPORT,
                                       bleAppContext.BleApplicationContext_legacy.bleSecurityParam.encryptionKeySizeMin,
                                       bleAppContext.BleApplicationContext_legacy.bleSecurityParam.encryptionKeySizeMax,
                                       GAP_PAIRING_RESP_NONE);

    DT_INFO_MSG("BLE_Init done\r\n");
}

/* ── Scheduler glue ────────────────────────────────────────────────────────── */

void BLEStack_Process_Schedule(void)
{
    UTIL_SEQ_SetTask(1U << CFG_TASK_BLE_STACK, CFG_SEQ_PRIO_1);
}

static void BLEStack_Process(void)
{
    BLE_STACK_Tick();
}

void VTimer_Process(void)       { HAL_RADIO_TIMER_Tick(); }
void VTimer_Process_Schedule(void)
{
    UTIL_SEQ_SetTask(1U << CFG_TASK_VTIMER, CFG_SEQ_PRIO_0);
}

void NVM_Process(void)       { NVMDB_Tick(); }
void NVM_Process_Schedule(void)
{
    UTIL_SEQ_SetTask(1U << CFG_TASK_NVM, CFG_SEQ_PRIO_1);
}

void HAL_RADIO_TIMER_TxRxWakeUpCallback(void)  { VTimer_Process_Schedule(); }
void HAL_RADIO_TIMER_CpuWakeUpCallback(void)   { VTimer_Process_Schedule(); }

void HAL_RADIO_TxRxCallback(uint32_t flags)
{
    BLE_STACK_RadioHandler(flags);
    VTimer_Process_Schedule();
    NVM_Process_Schedule();
}

void HAL_RADIO_RRMCallback(uint32_t ble_irq_status)
{
    BLE_STACK_RRMHandler(ble_irq_status);
}

void BLE_STACK_ProcessRequest(void) { BLEStack_Process_Schedule(); }

/* ── APP_BLE_Init ──────────────────────────────────────────────────────────── */

void APP_BLE_Init(void)
{
    UTIL_SEQ_RegTask(1U << CFG_TASK_BLE_STACK,   UTIL_SEQ_RFU, BLEStack_Process);
    UTIL_SEQ_RegTask(1U << CFG_TASK_VTIMER,      UTIL_SEQ_RFU, VTimer_Process);
    UTIL_SEQ_RegTask(1U << CFG_TASK_NVM,         UTIL_SEQ_RFU, NVM_Process);
    ModulesInit();
    BLE_Init();

    GATT_CLIENT_APP_Init();

    bleAppContext.Device_Connection_Status = APP_BLE_IDLE;
    bleAppContext.BleApplicationContext_legacy.connectionHandle = 0xFFFFU;

    UTIL_SEQ_RegTask(1U << CFG_TASK_START_SCAN_ID, UTIL_SEQ_RFU, Scan_Request);
    UTIL_SEQ_RegTask(1U << CFG_TASK_CONN_DEV_1_ID, UTIL_SEQ_RFU, Connect_Request);
    UTIL_SEQ_RegTask(1U << CFG_TASK_CONN_UPDATE_ID, UTIL_SEQ_RFU, Connection_Update);
    UTIL_SEQ_RegTask(1U << CFG_TASK_PHY_UPDATE_ID,  UTIL_SEQ_RFU, PHY_Update_Task);

    UTIL_SEQ_SetTask(1U << CFG_TASK_START_SCAN_ID, CFG_SEQ_PRIO_0);
}

/* ── HCI event dispatcher ──────────────────────────────────────────────────── */

void BLEEVT_App_Notification(const hci_pckt *hci_pckt)
{
    hci_event_pckt    *p_event_pckt;
    hci_le_meta_event *p_meta_evt;
    void              *event_data;

    if (hci_pckt->type != HCI_EVENT_PKT_TYPE &&
        hci_pckt->type != HCI_EVENT_EXT_PKT_TYPE) return;

    p_event_pckt = (hci_event_pckt *)hci_pckt->data;

    if (hci_pckt->type == HCI_EVENT_PKT_TYPE) {
        event_data = p_event_pckt->data;
    } else {
        hci_event_ext_pckt *p = (hci_event_ext_pckt *)hci_pckt->data;
        event_data = p->data;
    }

    switch (p_event_pckt->evt)
    {
    /* ── Disconnect ──────────────────────────────────────────────────────── */
    case HCI_DISCONNECTION_COMPLETE_EVT_CODE: {
        hci_disconnection_complete_event_rp0 *p_dc =
            (hci_disconnection_complete_event_rp0 *)p_event_pckt->data;

        GATT_CLIENT_APP_ConnHandle_Notif_evt_t notif = {
            .ConnOpcode = PEER_DISCON_HANDLE_EVT,
            .ConnHdl    = p_dc->Connection_Handle,
        };
        GATT_CLIENT_APP_Notification(&notif);

        if (p_dc->Connection_Handle ==
            bleAppContext.BleApplicationContext_legacy.connectionHandle) {
            bleAppContext.BleApplicationContext_legacy.connectionHandle = 0xFFFFU;
            bleAppContext.Device_Connection_Status = APP_BLE_IDLE;
            DT_INFO_MSG("Disconnected (reason 0x%02X) — restarting scan\r\n",
                        p_dc->Reason);
            UTIL_SEQ_SetTask(1U << CFG_TASK_START_SCAN_ID, CFG_SEQ_PRIO_0);
        }
        gap_cmd_resp_release();
        break;
    }

    /* ── LE meta ─────────────────────────────────────────────────────────── */
    case HCI_LE_META_EVT_CODE: {
        p_meta_evt = (hci_le_meta_event *)p_event_pckt->data;
        switch (p_meta_evt->subevent)
        {
        case HCI_LE_CONNECTION_UPDATE_COMPLETE_SUBEVT_CODE: {
            hci_le_connection_update_complete_event_rp0 *cu =
                (hci_le_connection_update_complete_event_rp0 *)p_meta_evt->data;
            DT_INFO_MSG("CI updated: %d.%02d ms\r\n",
                        (int)(cu->Connection_Interval * 125 / 100),
                        (int)(cu->Connection_Interval * 125 % 100));
            break;
        }
        case HCI_LE_PHY_UPDATE_COMPLETE_SUBEVT_CODE: {
            hci_le_phy_update_complete_event_rp0 *pu =
                (hci_le_phy_update_complete_event_rp0 *)p_meta_evt->data;
            gap_cmd_resp_release();
            DT_INFO_MSG("PHY update: TX=%u RX=%u status=0x%02X\r\n",
                        pu->TX_PHY, pu->RX_PHY, pu->Status);
            break;
        }
        case HCI_LE_ENHANCED_CONNECTION_COMPLETE_SUBEVT_CODE: {
            hci_le_enhanced_connection_complete_event_rp0 *ec =
                (hci_le_enhanced_connection_complete_event_rp0 *)p_meta_evt->data;
            connection_complete_event(ec->Status, ec->Connection_Handle, ec->Role,
                                      ec->Peer_Address_Type, ec->Peer_Address,
                                      ec->Connection_Interval, ec->Peripheral_Latency,
                                      ec->Supervision_Timeout);
            break;
        }
        case HCI_LE_CONNECTION_COMPLETE_SUBEVT_CODE: {
            hci_le_connection_complete_event_rp0 *cc =
                (hci_le_connection_complete_event_rp0 *)p_meta_evt->data;
            connection_complete_event(cc->Status, cc->Connection_Handle, cc->Role,
                                      cc->Peer_Address_Type, cc->Peer_Address,
                                      cc->Connection_Interval, cc->Peripheral_Latency,
                                      cc->Supervision_Timeout);
            break;
        }
        case HCI_LE_ADVERTISING_REPORT_SUBEVT_CODE: {
            hci_le_advertising_report_event_rp0 *ar =
                (hci_le_advertising_report_event_rp0 *)p_meta_evt->data;
            if (analyse_adv_report(ar->Advertising_Report.Data_Length,
                                   ar->Advertising_Report.Data_RSSI,
                                   ar->Advertising_Report.Address_Type,
                                   ar->Advertising_Report.Address) == 1U) {
                aci_gap_terminate_proc(GAP_GENERAL_DISCOVERY_PROC);
            }
            break;
        }
        case HCI_LE_EXTENDED_ADVERTISING_REPORT_SUBEVT_CODE: {
            hci_le_extended_advertising_report_event_rp0 *ea =
                (hci_le_extended_advertising_report_event_rp0 *)p_meta_evt->data;
            if (analyse_adv_report(ea->Extended_Advertising_Report.Data_Length,
                                   ea->Extended_Advertising_Report.Data,
                                   ea->Extended_Advertising_Report.Address_Type,
                                   ea->Extended_Advertising_Report.Address) != 0U) {
                APP_BLE_Procedure_Gap_Central(PROC_GAP_CENTRAL_SCAN_TERMINATE);
            }
            break;
        }
        /* Trigger PHY 2M once DLE negotiation is symmetric (Tx=Rx=251). */
        case HCI_LE_DATA_LENGTH_CHANGE_SUBEVT_CODE: {
            hci_le_data_length_change_event_rp0 *dl =
                (hci_le_data_length_change_event_rp0 *)p_meta_evt->data;
            DT_INFO_MSG("DLE: MaxTxOctets=%u MaxRxOctets=%u\r\n",
                        dl->MaxTxOctets, dl->MaxRxOctets);
            if (dl->MaxTxOctets == 251U && dl->MaxRxOctets == 251U) {
                UTIL_SEQ_SetTask(1U << CFG_TASK_PHY_UPDATE_ID, CFG_SEQ_PRIO_0);
            }
            break;
        }
        default:
            break;
        }
        break;
    } /* HCI_LE_META_EVT_CODE */

    /* ── Vendor events ───────────────────────────────────────────────────── */
    case HCI_VENDOR_EVT_CODE: {
        aci_blecore_event *p_blecore = (aci_blecore_event *)event_data;
        switch (p_blecore->ecode)
        {
        case ACI_L2CAP_CONNECTION_UPDATE_REQ_VSEVT_CODE: {
            aci_l2cap_connection_update_req_event_rp0 *req =
                (aci_l2cap_connection_update_req_event_rp0 *)p_blecore->data;
            aci_l2cap_connection_parameter_update_resp(
                req->Connection_Handle,
                req->Connection_Interval_Min, req->Connection_Interval_Max,
                req->Max_Latency, req->Timeout_Multiplier,
                CONN_CE_LENGTH_MS(10), CONN_CE_LENGTH_MS(10),
                req->Identifier, 0x01);
            break;
        }
        case ACI_GAP_PROC_COMPLETE_VSEVT_CODE: {
            aci_gap_proc_complete_event_rp0 *gp =
                (aci_gap_proc_complete_event_rp0 *)p_blecore->data;
            if (gp->Procedure_Code == GAP_GENERAL_DISCOVERY_PROC &&
                gp->Status == 0x00U) {
                UTIL_SEQ_SetTask(1U << CFG_TASK_CONN_DEV_1_ID, CFG_SEQ_PRIO_0);
            }
            break;
        }
        case ACI_HAL_END_OF_RADIO_ACTIVITY_VSEVT_CODE:
            break;
        default:
            break;
        }
        break;
    } /* HCI_VENDOR_EVT_CODE */

    case HCI_HARDWARE_ERROR_EVT_CODE: {
        hci_hardware_error_event_rp0 *he =
            (hci_hardware_error_event_rp0 *)p_event_pckt->data;
        if (he->Hardware_Code <= 0x03U) NVIC_SystemReset();
        break;
    }

    default:
        break;
    }
}

/* ── GAP procedure helpers ─────────────────────────────────────────────────── */

static void connection_complete_event(uint8_t Status, uint16_t Connection_Handle,
                                      uint8_t Role,
                                      uint8_t Peer_Address_Type, uint8_t Peer_Address[6],
                                      uint16_t Connection_Interval,
                                      uint16_t Peripheral_Latency,
                                      uint16_t Supervision_Timeout)
{
    GATT_CLIENT_APP_ConnHandle_Notif_evt_t notif;
    (void)Peer_Address_Type;
    (void)Peer_Address;
    (void)Peripheral_Latency;
    (void)Supervision_Timeout;

    if (Status != 0U) {
        DT_INFO_MSG("Connect failed: 0x%02X\r\n", Status);
        bleAppContext.Device_Connection_Status = APP_BLE_IDLE;
        return;
    }

    DT_INFO_MSG("Connected: handle=0x%04X CI=%d.%02d ms\r\n",
                Connection_Handle,
                (int)(Connection_Interval * 125 / 100),
                (int)(Connection_Interval * 125 % 100));

    if (Role == 0x00U) {   /* 0x00 = Central (we are the initiator) */
        bleAppContext.Device_Connection_Status = APP_BLE_CONNECTED_CLIENT;

        notif.ConnOpcode = PEER_CONN_HANDLE_EVT;
        notif.ConnHdl    = Connection_Handle;
        GATT_CLIENT_APP_Notification(&notif);

        GATT_CLIENT_APP_Discover_services(Connection_Handle);
    } else {
        bleAppContext.Device_Connection_Status = APP_BLE_CONNECTED_SERVER;
    }
    bleAppContext.BleApplicationContext_legacy.connectionHandle = Connection_Handle;
}

void APP_BLE_Procedure_Gap_General(ProcGapGeneralId_t ProcGapGeneralId)
{
    tBleStatus status;
    if (ProcGapGeneralId == PROC_GAP_GEN_CONN_TERMINATE) {
        status = aci_gap_terminate(
            bleAppContext.BleApplicationContext_legacy.connectionHandle,
            BLE_ERROR_TERMINATED_REMOTE_USER);
        if (status == BLE_STATUS_SUCCESS) gap_cmd_resp_wait();
    } else if (ProcGapGeneralId == PROC_GATT_EXCHANGE_CONFIG) {
        aci_gatt_clt_exchange_config(
            bleAppContext.BleApplicationContext_legacy.connectionHandle);
    }
}

void APP_BLE_Procedure_Gap_Central(ProcGapCentralId_t ProcGapCentralId)
{
    tBleStatus status;
    uint32_t paramA, paramB;

    if (ProcGapCentralId == PROC_GAP_CENTRAL_SCAN_START) {
        paramA = SCAN_INT_MS(500);
        paramB = SCAN_WIN_MS(500);
        status = aci_gap_set_scan_configuration(DUPLICATE_FILTER_ENABLED, 0x00,
                                                 LE_1M_PHY_BIT, HCI_SCAN_TYPE_ACTIVE,
                                                 paramA, paramB);
        (void)status;
        aci_gap_start_procedure(GAP_GENERAL_DISCOVERY_PROC, LE_1M_PHY_BIT, 0, 0);
        bleAppContext.Device_Connection_Status = APP_BLE_SCANNING;
    } else if (ProcGapCentralId == PROC_GAP_CENTRAL_SCAN_TERMINATE) {
        aci_gap_terminate_proc(GAP_GENERAL_DISCOVERY_PROC);
        bleAppContext.Device_Connection_Status = APP_BLE_IDLE;
    }
}

static void gap_cmd_resp_release(void)
{
    UTIL_SEQ_SetEvt(1U << CFG_IDLEEVT_PROC_GAP_COMPLETE);
}

static void gap_cmd_resp_wait(void)
{
    UTIL_SEQ_WaitEvt(1U << CFG_IDLEEVT_PROC_GAP_COMPLETE);
}

/* ── Scan / connect / CI update / PHY update tasks ─────────────────────────── */

static void Scan_Request(void)
{
    tBleStatus result;
    if (bleAppContext.Device_Connection_Status == APP_BLE_CONNECTED_CLIENT) return;

    result = aci_gap_set_scan_configuration(DUPLICATE_FILTER_ENABLED, 0x00,
                                             LE_1M_PHY_BIT, HCI_SCAN_TYPE_PASSIVE,
                                             SCAN_INT_MS(500U), SCAN_WIN_MS(500U));
    (void)result;
    aci_gap_start_procedure(GAP_GENERAL_DISCOVERY_PROC, LE_1M_PHY_BIT, 0, 0);
    DT_INFO_MSG("Scanning for \"Kuntur-Headstage\"\r\n");
}

static void Connect_Request(void)
{
    tBleStatus result;
    if (bleAppContext.deviceServerFound == 0U) return;

    result = aci_gap_set_connection_configuration(
        LE_1M_PHY_BIT,
        CONN_INT_MS(7.5), CONN_INT_MS(7.5),
        0,
        CONN_SUP_TIMEOUT_MS(5000),
        CONN_CE_LENGTH_MS(0), CONN_CE_LENGTH_MS(50));
    (void)result;

    result = aci_gap_create_connection(LE_1M_PHY_BIT,
                                        bleAppContext.deviceServerBdAddrType,
                                        bleAppContext.a_deviceServerBdAddr);
    if (result == BLE_STATUS_SUCCESS) {
        bleAppContext.Device_Connection_Status = APP_BLE_LP_CONNECTING;
        DT_INFO_MSG("Connecting...\r\n");
    } else {
        DT_INFO_MSG("Connect cmd failed: 0x%02X\r\n", result);
        bleAppContext.Device_Connection_Status = APP_BLE_IDLE;
    }
}

static void Connection_Update(void)
{
    aci_gap_start_connection_update(
        bleAppContext.BleApplicationContext_legacy.connectionHandle,
        CONN_INT_MS(7.5), CONN_INT_MS(7.5),
        0, 0x3E8, 0x0000, 0x0280);
}

/* Called after symmetric DLE event confirms PDU 251 on both sides. */
static void PHY_Update_Task(void)
{
    tBleStatus status = hci_le_set_phy(
        bleAppContext.BleApplicationContext_legacy.connectionHandle,
        0,
        HCI_TX_PHYS_LE_2M_PREF,
        HCI_RX_PHYS_LE_2M_PREF,
        0);
    if (status == BLE_STATUS_SUCCESS) {
        gap_cmd_resp_wait();   /* wait for HCI_LE_PHY_UPDATE_COMPLETE */
    } else {
        DT_INFO_MSG("PHY 2M request failed: 0x%02X\r\n", status);
    }
}

/* ── Advertisement name filter ─────────────────────────────────────────────── */

static uint8_t analyse_adv_report(uint8_t adv_data_size, uint8_t *p_adv_data,
                                   uint8_t address_type, uint8_t *p_address)
{
    static const char target[] = "Kuntur-Headstage";
    const uint8_t target_len  = (uint8_t)(sizeof(target) - 1U);
    uint8_t i = 0;

    while (i < adv_data_size) {
        uint8_t len  = p_adv_data[i];
        if (len == 0U || (uint16_t)(i + len) >= adv_data_size) break;
        uint8_t type = p_adv_data[i + 1U];

        if ((type == AD_TYPE_COMPLETE_LOCAL_NAME ||
             type == AD_TYPE_SHORTENED_LOCAL_NAME) &&
            (len - 1U) == target_len &&
            memcmp(&p_adv_data[i + 2U], target, target_len) == 0) {

            bleAppContext.deviceServerFound      = 0x01U;
            bleAppContext.deviceServerBdAddrType = address_type;
            memcpy(bleAppContext.a_deviceServerBdAddr, p_address, BD_ADDR_SIZE);
            DT_INFO_MSG("Found \"%s\" @%02X:%02X:%02X:%02X:%02X:%02X\r\n",
                        target,
                        p_address[5], p_address[4], p_address[3],
                        p_address[2], p_address[1], p_address[0]);
            return 1U;
        }
        i += len + 1U;
    }
    return 0U;
}

/* ── CRC8 (retained from reference; declared in app_ble.h) ─────────────────── */

#if defined(__GNUC__) && !defined(__clang__)
uint8_t __attribute__((optimize("Os"))) APP_BLE_ComputeCRC8(uint8_t *DataPtr, uint8_t Datalen)
#else
uint8_t APP_BLE_ComputeCRC8(uint8_t *DataPtr, uint8_t Datalen)
#endif
{
    uint8_t i, j;
    const uint8_t poly = 0x97U;
    uint8_t crc = 0x00U;
    for (i = 0; i < Datalen; i++) {
        crc ^= DataPtr[i];
        for (j = 0; j < 8U; j++) {
            crc = (crc & 0x80U) ? (uint8_t)((crc << 1U) ^ poly) : (uint8_t)(crc << 1U);
        }
    }
    return crc;
}
