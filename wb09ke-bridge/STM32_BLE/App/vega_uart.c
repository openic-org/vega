/*
 * vega_uart.c — interrupt-driven UART TX ring buffer.
 *
 * Single-producer (main context) / single-consumer (TXE ISR) lockless ring
 * buffer. On Cortex-M0+ all 32-bit aligned reads/writes are atomic, and
 * uint16_t reads/writes are atomic if naturally aligned — which they are here.
 *
 * Head is written only by the main context; tail only by the TXE ISR.
 * No mutex needed.
 */

#include "vega_uart.h"
#include "vega_bridge_app.h"
#include "stm32wb0x.h"
#include "stm32wb0x_ll_usart.h"

#define BUF_MASK  (VEGA_UART_TX_BUF_SIZE - 1U)

static uint8_t           s_buf[VEGA_UART_TX_BUF_SIZE];
static volatile uint16_t s_head;   /* next write slot  — main context only */
static volatile uint16_t s_tail;   /* next read  slot  — TXE ISR only      */

void VEGA_UART_Init(void)
{
    s_head = 0;
    s_tail = 0;
}

void VEGA_UART_Write(const uint8_t *data, uint16_t len)
{
    uint16_t head = s_head;
    for (uint16_t i = 0; i < len; i++) {
        uint16_t next = (head + 1U) & BUF_MASK;
        if (next == s_tail) break;          /* buffer full — drop remainder */
        s_buf[head] = data[i];
        head = next;
    }
    /* Commit the new head before enabling the IRQ. */
    s_head = head;
    LL_USART_EnableIT_TXE(USART1);
}

uint8_t VEGA_UART_TxBytePop(uint8_t *byte)
{
    uint16_t tail = s_tail;
    if (tail == s_head) return 0;           /* empty */
    *byte  = s_buf[tail];
    s_tail = (tail + 1U) & BUF_MASK;
    return 1;
}

/* ── Command-frame RX (pc-app -> bridge) ─────────────────────────────────────
 * Runs entirely in ISR context (called from USART1_IRQHandler's RXNE path).
 * Single-producer, no concurrency concerns — the debug-console path
 * (UartRxCpltCallback) runs in the same ISR, never concurrently with this.
 */

#define CMD_MAGIC_0      0xCCU
#define CMD_MAGIC_1      0x33U

typedef enum
{
    RX_IDLE,
    RX_GOT_MAGIC0,
    RX_LEN,
    RX_PAYLOAD,
    RX_DISCARD,   /* oversized/malformed length — swallow the rest, don't dispatch */
} RxState_t;

static RxState_t s_rx_state = RX_IDLE;
static uint8_t   s_rx_buf[VEGA_UART_CMD_MAX_PAYLOAD];
static uint8_t   s_rx_len;
static uint8_t   s_rx_idx;

uint8_t VEGA_UART_RxByte(uint8_t byte)
{
    switch (s_rx_state)
    {
    case RX_IDLE:
        if (byte == CMD_MAGIC_0)
        {
            s_rx_state = RX_GOT_MAGIC0;
            return 1;
        }
        return 0;   /* not a command frame — let the debug console have it */

    case RX_GOT_MAGIC0:
        /* 0xCC never appears in ordinary debug-console ASCII input, so the
         * magic-0 byte above was safely swallowed. If this byte isn't the
         * real magic-1, it can't be handed back to the debug console either
         * (already consumed) — just resync on it in case it starts a new
         * frame. */
        s_rx_state = (byte == CMD_MAGIC_1) ? RX_LEN
                    : (byte == CMD_MAGIC_0) ? RX_GOT_MAGIC0
                    : RX_IDLE;
        return 1;

    case RX_LEN:
        s_rx_idx = 0;
        s_rx_len = byte;
        if (byte == 0U)
            s_rx_state = RX_IDLE;      /* empty frame, nothing follows */
        else if (byte > VEGA_UART_CMD_MAX_PAYLOAD)
            s_rx_state = RX_DISCARD;   /* oversized — s_rx_len doubles as remaining-count */
        else
            s_rx_state = RX_PAYLOAD;
        return 1;

    case RX_PAYLOAD:
        s_rx_buf[s_rx_idx++] = byte;
        if (s_rx_idx >= s_rx_len)
        {
            VEGA_BRIDGE_OnCommandFrame(s_rx_buf, s_rx_len);
            s_rx_state = RX_IDLE;
        }
        return 1;

    case RX_DISCARD:
    default:
        if (--s_rx_len == 0U) s_rx_state = RX_IDLE;
        return 1;
    }
}
