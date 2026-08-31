/*
 * vega_uart.c — interrupt-driven UART TX ring buffer.
 *
 * Single-producer (main context) / single-consumer (TXE ISR) lockless ring
 * buffer. On Cortex-M0+ all 32-bit aligned reads/writes are atomic, and
 * uint16_t reads/writes are atomic if naturally aligned — which they are here.
 *
 * Head is written only by the main context; tail only by the TXE ISR.
 * No mutex needed.
 *
 * The truncation counters are the one exception: VEGA_UART_Write() is
 * reachable from ISR context when CFG_DEBUG_APP_TRACE is on (DT_INFO_MSG
 * inside USART1_IRQHandler), and the M0+ has no atomic read-modify-write, so
 * they are incremented under a short critical section. Only the drop path
 * pays for it.
 */

#include <stddef.h>
#include "vega_uart.h"
#include "vega_bridge_app.h"
#include "stm32wb0x.h"
#include "stm32wb0x_ll_usart.h"
#include "stm32wb0x_hal.h"   /* HAL_GetTick() — RX_FRAME_TIMEOUT_MS below */

#define BUF_MASK  (VEGA_UART_TX_BUF_SIZE - 1U)

static uint8_t           s_buf[VEGA_UART_TX_BUF_SIZE];
static volatile uint16_t s_head;   /* next write slot  — main context only */
static volatile uint16_t s_tail;   /* next read  slot  — TXE ISR only      */

/* Truncation accounting — see the note in vega_uart.h. Zeroed at startup by
 * the C runtime; deliberately not touched by VEGA_UART_Init() so a re-init
 * cannot erase the history. */
static volatile uint32_t s_drop_bytes;    /* bytes discarded, ring was full   */
static volatile uint32_t s_drop_frames;   /* Write() calls that truncated     */

void VEGA_UART_Init(void)
{
    s_head = 0;
    s_tail = 0;
}

void VEGA_UART_Write(const uint8_t *data, uint16_t len)
{
    uint16_t head = s_head;
    uint16_t i;
    for (i = 0; i < len; i++) {
        uint16_t next = (head + 1U) & BUF_MASK;
        if (next == s_tail) break;          /* buffer full — drop remainder */
        s_buf[head] = data[i];
        head = next;
    }
    /* Commit the new head before enabling the IRQ. */
    s_head = head;

    if (i < len) {
        /* Truncated. (len - i) bytes of this frame never reach the wire, and
         * the frame already committed above is now short of its length field
         * — the pc-app will resync on the next magic pair. Nothing can be
         * done about it here; the point is that it stops being silent. */
        uint32_t primask = __get_PRIMASK();
        __disable_irq();
        s_drop_bytes  += (uint32_t)(len - i);
        s_drop_frames += 1U;
        __set_PRIMASK(primask);
    }

    LL_USART_EnableIT_TXE(USART1);
}

void VEGA_UART_GetDropStats(uint32_t *p_bytes, uint32_t *p_frames)
{
    /* Each load is a single aligned 32-bit read, atomic on the M0+, so no
     * critical section is needed to read them — but the pair is not sampled
     * atomically with respect to each other. Treat a bytes/frames ratio taken
     * across a live drop burst as approximate. */
    if (p_bytes  != NULL) *p_bytes  = s_drop_bytes;
    if (p_frames != NULL) *p_frames = s_drop_frames;
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

/* Timeout backstop for a stuck partial frame — see vega_uart.h's comment on
 * VEGA_UART_RxReset(). At 2 Mbaud a legitimately-continuous frame's byte
 * gap is ~5 us; 5 ms is ~1000x that margin, so any real transmission never
 * trips this, while a desynced parser can't wait longer than 5 ms for a
 * byte that isn't coming. Still far short of the pc-app's ~2000 ms
 * ACK_TIMEOUT_MS retry gap, so a retry always finds the parser at RX_IDLE
 * — it never lands on a still-stuck frame. */
#define RX_FRAME_TIMEOUT_MS  5U
static uint32_t s_rx_last_byte_tick;

void VEGA_UART_RxReset(void)
{
    s_rx_state = RX_IDLE;
}

uint8_t VEGA_UART_RxByte(uint8_t byte)
{
    uint32_t now = HAL_GetTick();
    if (s_rx_state != RX_IDLE && (now - s_rx_last_byte_tick) > RX_FRAME_TIMEOUT_MS)
    {
        /* Stale partial frame — abandon it so `byte` below is evaluated
         * fresh against RX_IDLE instead of being consumed as data for a
         * frame that's already missing one. */
        s_rx_state = RX_IDLE;
    }
    s_rx_last_byte_tick = now;

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
