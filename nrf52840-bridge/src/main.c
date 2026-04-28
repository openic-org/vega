/*
 * vega_bridge — nRF52840 BLE Central → USB CDC bridge
 *
 * Connects to the Kuntur STM32WB09 as a BLE central ("Kuntur-N"),
 * subscribes to the 0xFFF2 notify characteristic, and forwards every
 * 244-byte StreamDataPacket_t to the PC via USB CDC ACM.
 *
 * Frame format over USB (for PC re-sync):
 *   [0xAA][0x55][len_lo][len_hi][payload...]
 *
 * USB TX uses an IRQ-driven ring buffer so the USB TX thread never
 * blocks when the PC application is not reading.
 *
 * LEDs (nRF52840 DK, active-low):
 *   LED0 — BLE connected
 *   LED1 — USB CDC open (DTR asserted by PC)
 *   LED2 — data flowing (toggles each packet)
 *   LED3 — overflow / error
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/ring_buffer.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/usb/usb_device.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/logging/log.h>
#include <string.h>

LOG_MODULE_REGISTER(vega_bridge, LOG_LEVEL_INF);

/* ── Constants ─────────────────────────────────────────────────────────────── */

#define PACKET_SIZE      244U
#define FRAME_HDR_SIZE   4U
#define FRAME_SIZE       (FRAME_HDR_SIZE + PACKET_SIZE)
#define QUEUE_DEPTH      32U

/* USB TX ring buffer: holds 16 complete frames without blocking */
#define USB_TX_RB_SIZE   (FRAME_SIZE * 16U)

static const char TARGET_NAME[] = "Kuntur-N";

static struct bt_uuid_16 stream_svc_uuid  = BT_UUID_INIT_16(0xFFF0);
static struct bt_uuid_16 notify_char_uuid = BT_UUID_INIT_16(0xFFF2);

/* ── LEDs ───────────────────────────────────────────────────────────────────── */

static const struct gpio_dt_spec led_ble  = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec led_usb  = GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios);
static const struct gpio_dt_spec led_data = GPIO_DT_SPEC_GET(DT_ALIAS(led2), gpios);
static const struct gpio_dt_spec led_err  = GPIO_DT_SPEC_GET(DT_ALIAS(led3), gpios);

static void leds_init(void)
{
    gpio_pin_configure_dt(&led_ble,  GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&led_usb,  GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&led_data, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&led_err,  GPIO_OUTPUT_INACTIVE);
}

/* ── BLE→USB message queue ──────────────────────────────────────────────────── */

K_MSGQ_DEFINE(ble_msgq, PACKET_SIZE, QUEUE_DEPTH, 4);

/* ── USB CDC state ──────────────────────────────────────────────────────────── */

static const struct device *cdc_dev;
static bool                 usb_dtr;

/* IRQ-driven TX ring buffer — filled by usb_tx_fn, drained by CDC TX IRQ */
RING_BUF_DECLARE(usb_tx_rb, USB_TX_RB_SIZE);
static atomic_t usb_tx_irq_active = ATOMIC_INIT(0);

/* ── CDC IRQ handler ────────────────────────────────────────────────────────── */

static void cdc_irq_handler(const struct device *dev, void *user_data)
{
    ARG_UNUSED(user_data);

    while (uart_irq_update(dev) && uart_irq_is_pending(dev)) {

        /* TX: drain the ring buffer into the CDC FIFO */
        if (uart_irq_tx_ready(dev)) {
            uint8_t  *data;
            uint32_t  claim_len;

            claim_len = ring_buf_get_claim(&usb_tx_rb, &data, 64U);
            if (claim_len > 0) {
                int sent = uart_fifo_fill(dev, data, (int)claim_len);
                ring_buf_get_finish(&usb_tx_rb, (uint32_t)MAX(sent, 0));
            } else {
                /* Ring buffer empty — disable TX IRQ until more data arrives */
                uart_irq_tx_disable(dev);
                atomic_set(&usb_tx_irq_active, 0);
            }
        }

        /* RX: used only for DTR line control detection */
        if (uart_irq_rx_ready(dev)) {
            uint8_t dummy;
            uart_fifo_read(dev, &dummy, 1);
        }
    }
}

/* ── Non-blocking USB frame write ───────────────────────────────────────────── */

static void usb_write_frame(const uint8_t *payload, uint16_t payload_len)
{
    uint8_t frame[FRAME_SIZE];
    frame[0] = 0xAA;
    frame[1] = 0x55;
    frame[2] = (uint8_t)(payload_len & 0xFF);
    frame[3] = (uint8_t)((payload_len >> 8) & 0xFF);
    memcpy(&frame[4], payload, payload_len);

    uint32_t written = ring_buf_put(&usb_tx_rb, frame, FRAME_SIZE);
    if (written < FRAME_SIZE) {
        gpio_pin_set_dt(&led_err, 1);
        LOG_WRN("USB TX ring full — frame dropped");
    } else {
        gpio_pin_set_dt(&led_err, 0);
    }

    /* Kick the TX IRQ if not already running */
    if (atomic_cas(&usb_tx_irq_active, 0, 1)) {
        uart_irq_tx_enable(cdc_dev);
    }
}

/* ── DTR poll ───────────────────────────────────────────────────────────────── */

static void poll_dtr(void)
{
    uint32_t dtr = 0;
    uart_line_ctrl_get(cdc_dev, UART_LINE_CTRL_DTR, &dtr);
    bool new_dtr = (bool)dtr;
    if (new_dtr != usb_dtr) {
        usb_dtr = new_dtr;
        gpio_pin_set_dt(&led_usb, usb_dtr ? 1 : 0);
        LOG_INF("DTR %s", usb_dtr ? "set" : "cleared");
        if (!usb_dtr) {
            /* PC closed port — flush TX ring buffer to avoid stale data */
            ring_buf_reset(&usb_tx_rb);
        }
    }
}

/* ── Connection + GATT state ────────────────────────────────────────────────── */

static struct bt_conn                *current_conn;
static struct bt_gatt_discover_params disc_params;
static struct bt_gatt_subscribe_params sub_params;
static uint16_t                       notify_value_handle;

/* ── BLE notification callback ──────────────────────────────────────────────── */

static uint8_t notify_cb(struct bt_conn *conn,
                          struct bt_gatt_subscribe_params *params,
                          const void *data, uint16_t length)
{
    if (!data) {
        LOG_WRN("Unsubscribed from 0xFFF2");
        return BT_GATT_ITER_STOP;
    }

    if (length != PACKET_SIZE) {
        LOG_WRN("Unexpected packet size: %u", length);
        return BT_GATT_ITER_CONTINUE;
    }

    if (k_msgq_put(&ble_msgq, data, K_NO_WAIT) != 0) {
        gpio_pin_set_dt(&led_err, 1);
        LOG_WRN("BLE queue full — packet dropped");
    } else {
        gpio_pin_toggle_dt(&led_data);
    }

    return BT_GATT_ITER_CONTINUE;
}

/* ── GATT discovery ─────────────────────────────────────────────────────────── */

static uint8_t descriptor_disc_cb(struct bt_conn *conn,
                                   const struct bt_gatt_attr *attr,
                                   struct bt_gatt_discover_params *params)
{
    if (!attr) {
        LOG_ERR("CCCD not found");
        return BT_GATT_ITER_STOP;
    }
    LOG_INF("CCCD handle: 0x%04x", attr->handle);
    sub_params.notify       = notify_cb;
    sub_params.value        = BT_GATT_CCC_NOTIFY;
    sub_params.value_handle = notify_value_handle;
    sub_params.ccc_handle   = attr->handle;
    int err = bt_gatt_subscribe(conn, &sub_params);
    if (err && err != -EALREADY) {
        LOG_ERR("Subscribe failed: %d", err);
    } else {
        LOG_INF("Subscribed to 0xFFF2 — streaming started");
    }
    return BT_GATT_ITER_STOP;
}

static uint8_t char_disc_cb(struct bt_conn *conn,
                              const struct bt_gatt_attr *attr,
                              struct bt_gatt_discover_params *params)
{
    if (!attr) {
        LOG_ERR("Characteristic 0xFFF2 not found");
        return BT_GATT_ITER_STOP;
    }
    const struct bt_gatt_chrc *chrc = (struct bt_gatt_chrc *)attr->user_data;
    notify_value_handle = chrc->value_handle;
    LOG_INF("0xFFF2 value handle: 0x%04x", notify_value_handle);

    static struct bt_uuid_16 cccd_uuid = BT_UUID_INIT_16(BT_UUID_GATT_CCC_VAL);
    disc_params.uuid         = &cccd_uuid.uuid;
    disc_params.type         = BT_GATT_DISCOVER_DESCRIPTOR;
    disc_params.start_handle = notify_value_handle + 1;
    disc_params.end_handle   = BT_ATT_LAST_ATTRIBUTE_HANDLE;
    disc_params.func         = descriptor_disc_cb;
    bt_gatt_discover(conn, &disc_params);
    return BT_GATT_ITER_STOP;
}

static uint8_t service_disc_cb(struct bt_conn *conn,
                                const struct bt_gatt_attr *attr,
                                struct bt_gatt_discover_params *params)
{
    if (!attr) {
        LOG_ERR("Service 0xFFF0 not found");
        return BT_GATT_ITER_STOP;
    }
    LOG_INF("Service 0xFFF0 handle: 0x%04x", attr->handle);
    const struct bt_gatt_service_val *svc = (struct bt_gatt_service_val *)attr->user_data;
    disc_params.uuid         = &notify_char_uuid.uuid;
    disc_params.type         = BT_GATT_DISCOVER_CHARACTERISTIC;
    disc_params.start_handle = attr->handle + 1;
    disc_params.end_handle   = svc->end_handle;
    disc_params.func         = char_disc_cb;
    bt_gatt_discover(conn, &disc_params);
    return BT_GATT_ITER_STOP;
}

static void start_discovery(struct bt_conn *conn)
{
    disc_params.uuid         = &stream_svc_uuid.uuid;
    disc_params.type         = BT_GATT_DISCOVER_PRIMARY;
    disc_params.start_handle = BT_ATT_FIRST_ATTRIBUTE_HANDLE;
    disc_params.end_handle   = BT_ATT_LAST_ATTRIBUTE_HANDLE;
    disc_params.func         = service_disc_cb;
    int err = bt_gatt_discover(conn, &disc_params);
    if (err) {
        LOG_ERR("Discovery start failed: %d", err);
    }
}

/* ── MTU exchange ───────────────────────────────────────────────────────────── */

static struct bt_gatt_exchange_params mtu_params;

static void mtu_exchange_cb(struct bt_conn *conn, uint8_t err,
                              struct bt_gatt_exchange_params *params)
{
    if (err) {
        LOG_WRN("MTU exchange failed: %d — starting discovery anyway", err);
    } else {
        LOG_INF("MTU exchanged: %u bytes", bt_gatt_get_mtu(conn));
    }
    start_discovery(conn);
}

/* ── Connection parameters ──────────────────────────────────────────────────── */

static const struct bt_le_conn_param fast_conn_params =
    BT_LE_CONN_PARAM_INIT(6, 6, 0, 500);   /* 7.5 ms CI, 5 s timeout */

/* ── Connection callbacks ───────────────────────────────────────────────────── */

static void le_param_updated_cb(struct bt_conn *conn, uint16_t interval,
                                  uint16_t latency, uint16_t timeout)
{
    /* Avoid %f — picolibc in Zephyr log doesn't support it.
     * interval is in units of 1.25 ms: multiply by 5 and divide by 4. */
    uint32_t ci_ms_x100 = (uint32_t)interval * 125U;  /* × 1.25 ms, ×100 */
    LOG_INF("CI updated: %u.%02u ms  latency=%d  timeout=%d ms",
            ci_ms_x100 / 100U, ci_ms_x100 % 100U, latency, timeout * 10);
}

BT_CONN_CB_DEFINE(param_callbacks) = {
    .le_param_updated = le_param_updated_cb,
};

static void connected_cb(struct bt_conn *conn, uint8_t err)
{
    if (err) {
        LOG_ERR("Connection failed: %d", err);
        bt_conn_unref(conn);
        current_conn = NULL;
        return;
    }

    current_conn = bt_conn_ref(conn);

    struct bt_conn_info info;
    if (bt_conn_get_info(conn, &info) == 0 && info.le.interval > 0) {
        uint32_t ci_x100 = (uint32_t)info.le.interval * 125U;
        LOG_INF("Connected: initial CI=%u.%02u ms",
                ci_x100 / 100U, ci_x100 % 100U);
    } else {
        LOG_INF("Connected");
    }
    gpio_pin_set_dt(&led_ble, 1);

    /* Request 7.5 ms CI as central — STM32 CPUP is suppressed in NORDIC_HF */
    bt_conn_le_param_update(conn, &fast_conn_params);

    /* Note: bt_conn_le_phy_update() fails with SDC in NCS 3.3 central role.
     * 1M PHY is sufficient for 30 kSPS at 7.5 ms CI (~1 ms/pkt, 7 pkts/CI). */

    /* Exchange MTU before discovery */
    mtu_params.func = mtu_exchange_cb;
    int mtu_err = bt_gatt_exchange_mtu(conn, &mtu_params);
    if (mtu_err) {
        LOG_WRN("MTU request failed: %d", mtu_err);
        start_discovery(conn);
    }
}

static void disconnected_cb(struct bt_conn *conn, uint8_t reason)
{
    LOG_INF("Disconnected (reason 0x%02x)", reason);
    gpio_pin_set_dt(&led_ble,  0);
    gpio_pin_set_dt(&led_data, 0);
    bt_conn_unref(current_conn);
    current_conn = NULL;

    /* Drain stale BLE packets */
    uint8_t dummy[PACKET_SIZE];
    while (k_msgq_get(&ble_msgq, dummy, K_NO_WAIT) == 0) {}

    /* Restart scan */
    bt_le_scan_start(BT_LE_SCAN_ACTIVE, NULL);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
    .connected    = connected_cb,
    .disconnected = disconnected_cb,
};

/* ── Scan callback ──────────────────────────────────────────────────────────── */

static bool parse_ad_name(struct bt_data *data, void *user_data)
{
    bool *found = (bool *)user_data;
    if (data->type == BT_DATA_NAME_COMPLETE ||
        data->type == BT_DATA_NAME_SHORTENED) {
        size_t tlen = sizeof(TARGET_NAME) - 1;
        if (data->data_len == tlen &&
            memcmp(data->data, TARGET_NAME, tlen) == 0) {
            *found = true;
            return false;
        }
    }
    return true;
}

static void scan_cb(const bt_addr_le_t *addr, int8_t rssi,
                    uint8_t adv_type, struct net_buf_simple *buf)
{
    bool found = false;
    bt_data_parse(buf, parse_ad_name, &found);
    if (!found) return;

    LOG_INF("Found \"%s\" (RSSI %d) — connecting", TARGET_NAME, rssi);
    bt_le_scan_stop();

    struct bt_conn *conn;
    int err = bt_conn_le_create(addr, BT_CONN_LE_CREATE_CONN,
                                &fast_conn_params, &conn);
    if (err) {
        LOG_ERR("Connect failed: %d", err);
        bt_le_scan_start(BT_LE_SCAN_ACTIVE, NULL);
    } else {
        bt_conn_unref(conn);
    }
}

/* ── USB TX thread ──────────────────────────────────────────────────────────── */

#define USB_TX_STACK_SIZE  2048
K_THREAD_STACK_DEFINE(usb_tx_stack, USB_TX_STACK_SIZE);
static struct k_thread usb_tx_thread;

static void usb_tx_fn(void *p1, void *p2, void *p3)
{
    uint8_t pkt[PACKET_SIZE];

    while (true) {
        if (k_msgq_get(&ble_msgq, pkt, K_MSEC(200)) != 0) {
            poll_dtr();
            continue;
        }
        poll_dtr();
        if (!usb_dtr) {
            /* PC port not open — discard, don't fill the ring buffer */
            continue;
        }
        usb_write_frame(pkt, PACKET_SIZE);
    }
}

/* ── Main ───────────────────────────────────────────────────────────────────── */

int main(void)
{
    leds_init();
    LOG_INF("Vega Bridge starting");

    cdc_dev = DEVICE_DT_GET(DT_NODELABEL(cdc_acm_uart0));
    if (!device_is_ready(cdc_dev)) {
        LOG_ERR("CDC ACM not ready");
        return -ENODEV;
    }

    uart_line_ctrl_set(cdc_dev, UART_LINE_CTRL_DCD, 1);
    uart_line_ctrl_set(cdc_dev, UART_LINE_CTRL_DSR, 1);

    int err = usb_enable(NULL);
    if (err) {
        LOG_ERR("USB enable failed: %d", err);
        return err;
    }
    k_sleep(K_MSEC(1000));

    /* Register IRQ callback — handles both TX drain and RX (for DTR) */
    uart_irq_callback_user_data_set(cdc_dev, cdc_irq_handler, NULL);
    uart_irq_rx_enable(cdc_dev);

    k_thread_create(&usb_tx_thread, usb_tx_stack,
                    K_THREAD_STACK_SIZEOF(usb_tx_stack),
                    usb_tx_fn, NULL, NULL, NULL,
                    K_PRIO_PREEMPT(7), 0, K_NO_WAIT);
    k_thread_name_set(&usb_tx_thread, "usb_tx");

    err = bt_enable(NULL);
    if (err) {
        LOG_ERR("Bluetooth init failed: %d", err);
        return err;
    }
    LOG_INF("Bluetooth ready — scanning for \"%s\"", TARGET_NAME);

    err = bt_le_scan_start(BT_LE_SCAN_ACTIVE, scan_cb);
    if (err) {
        LOG_ERR("Scan start failed: %d", err);
        return err;
    }

    return 0;
}
