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
