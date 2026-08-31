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

/* ── Command-frame RX (pc-app -> bridge) ─────────────────────────────────────
 * See docs/interfaces/channel-selection-control-plane.md section 3.
 * Frame: 0xCC 0x33 <len> <payload...>, payload relayed verbatim to 0xFFF1.
 *
 * VEGA_UART_RxByte() is called from USART1_IRQHandler for every received
 * byte, before the existing debug-console path (UartRxCpltCallback). Returns
 * 1 if the byte was consumed as part of a command frame (caller must NOT
 * also forward it to the debug console), 0 otherwise (caller should forward
 * it to the debug console as before).
 *
 * On a complete frame, calls VEGA_BRIDGE_OnCommandFrame() (vega_bridge_app.h)
 * to hand the payload off to sequencer-task context — this function runs in
 * ISR context and must never call into the BLE stack directly. */

#define VEGA_UART_CMD_MAX_PAYLOAD  16U

uint8_t VEGA_UART_RxByte(uint8_t byte);

/* Forces the command-frame parser back to RX_IDLE, abandoning whatever
 * partial frame is in progress. Two callers:
 *   - stm32wb0x_it.c's USART1 ORE handler, immediately after clearing the
 *     overrun — an overrun means at least one byte was lost, so the parser
 *     can no longer trust its position within the current frame. Found
 *     2026-08-31: an ORE mid-payload let a *later* frame's 0xCC 0x33 magic
 *     get consumed as data instead of recognized as a new frame, corrupting
 *     a REG_WRITE16's staged high byte on the FPGA regbank.
 *   - VEGA_UART_RxByte() itself, as a timeout backstop (RX_FRAME_TIMEOUT_MS)
 *     for any other desync source an ORE doesn't cover. */
void VEGA_UART_RxReset(void);

/* ── TX-ring truncation counters ─────────────────────────────────────────────
 * VEGA_UART_Write() drops the remainder of a write when the ring is full.
 * That puts a TRUNCATED frame on the wire: the pc-app resynchronises on the
 * next magic pair and reads the result as a missing packet, indistinguishable
 * from one lost on air. These counters make the two distinguishable at the
 * source, which is the only place that knows.
 *
 * Free-running since boot; never reset. Diff two reads for a per-interval
 * figure. Both are readable over SWD without stopping the core.
 *
 * Deliberately NOT reported anywhere yet: the debug console is a no-op by
 * default (CFG_DEBUG_APP_TRACE, and it shares this wire with the data
 * stream), and sending them to the pc-app would be a new bridge->PC frame
 * type — a cross-boundary interface that wants a spec in docs/interfaces/
 * before it exists. Nothing here writes to the wire.
 *
 * Either pointer may be NULL. */
void VEGA_UART_GetDropStats(uint32_t *p_bytes, uint32_t *p_frames);

#endif /* VEGA_UART_H */
