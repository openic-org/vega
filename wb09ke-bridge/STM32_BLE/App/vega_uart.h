/*
 * vega_uart.h — interrupt-driven UART TX ring buffer for the Vega WB09KE bridge.
 *
 * Main context (BLE notification callback, printf) calls VEGA_UART_Write().
 * The USART1 TXE interrupt handler calls VEGA_UART_TxBytePop() to drain the buffer.
 *
 * VEGA_UART_TX_BUF_SIZE must be a power of 2.
 */

#ifndef VEGA_UART_H
#define VEGA_UART_H

#include <stdint.h>

#define VEGA_UART_TX_BUF_SIZE  4096U   /* must be power of 2 */

void    VEGA_UART_Init(void);

/* Queue bytes for TX; enables TXE interrupt to start draining. */
void    VEGA_UART_Write(const uint8_t *data, uint16_t len);

/* Called from USART1_IRQHandler when TXE is set.
 * Returns 1 if a byte was returned in *byte, 0 if the buffer is empty. */
uint8_t VEGA_UART_TxBytePop(uint8_t *byte);

#endif /* VEGA_UART_H */
