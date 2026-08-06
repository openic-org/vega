/*
 * stm32wb0x_it.c — interrupt service routines for the Vega WB09KE bridge.
 *
 * Identical to the reference DataThroughput client except that USART1_IRQHandler
 * also drains the TX ring buffer on TXE interrupts.  The TXE interrupt is enabled
 * by VEGA_UART_Write() and disabled here when the buffer runs empty, so the ISR
 * never fires when there is nothing to send.
 */

#include "app_conf.h"  /* must be first — see vega_bridge_app.c's identical comment; needed here for DT_INFO_MSG */
#include "main.h"
#include "stm32wb0x_it.h"
#include "hw_pka.h"
#include "ble_stack.h"
#include "miscutil.h"
#include "stm32wb0x_ll_usart.h"
#include "vega_uart.h"

extern PKA_HandleTypeDef hpka;

void NMI_Handler(void) {}

void HardFault_Handler(void)
{
    while (1) {}
}

void SVC_Handler(void) {}

void PendSV_Handler(void) {}

void SysTick_Handler(void)
{
    HAL_IncTick();
}

void USART1_IRQHandler(void)
{
    /* TX: drain ring buffer one byte per interrupt */
    if (LL_USART_IsEnabledIT_TXE(USART1) && LL_USART_IsActiveFlag_TXE(USART1)) {
        uint8_t byte;
        if (VEGA_UART_TxBytePop(&byte)) {
            LL_USART_TransmitData8(USART1, byte);
        } else {
            LL_USART_DisableIT_TXE(USART1);
        }
    }

    /* RX: command-frame parser gets first look (magic 0xCC 0x33 — never
     * appears in ordinary debug-console ASCII input); anything it doesn't
     * consume falls through to the debug-trace callback as before. */
    if (LL_USART_IsActiveFlag_RXNE(USART1)) {
        uint8_t data = LL_USART_ReceiveData8(USART1);
        if (!VEGA_UART_RxByte(data)) {
            UartRxCpltCallback(&data, 1);
        }
    }

    /* Overrun error (ORE): found 2026-08-06 diagnosing pc-app commands going
     * completely silent mid-session — every incoming byte after the overrun
     * is dropped because, per the USART reference manual, RXNE stops being
     * set for new data until ORE is explicitly cleared via ICR. Nothing here
     * ever cleared it, so one overrun (plausible at 2 Mbaud if the BLE
     * radio's own higher-priority ISR delays this one past a single byte
     * time, ~5 us, e.g. right as 30 kSPS streaming resumes) permanently
     * killed command reception for the rest of the session with zero log
     * output anywhere — exactly the observed symptom. Clearing it lets RX
     * self-heal; the log line confirms whether this is actually the cause. */
    if (LL_USART_IsActiveFlag_ORE(USART1)) {
        LL_USART_ClearFlag_ORE(USART1);
        DT_INFO_MSG("USART1: RX overrun (ORE) cleared\r\n");
    }
}

void PKA_IRQHandler(void)
{
    HAL_PKA_IRQHandler(&hpka);
}

void RADIO_TIMER_CPU_WKUP_IRQHandler(void)
{
    HAL_RADIO_TIMER_CPU_WKUP_IRQHandler();
}

void RADIO_TIMER_ERROR_IRQHandler(void)
{
    HAL_RADIO_TIMER_ERROR_IRQHandler();
}

void RADIO_TXRX_IRQHandler(void)
{
    HAL_RADIO_TXRX_IRQHandler();
}

void RADIO_TXRX_SEQ_IRQHandler(void)
{
    HAL_RADIO_TXRX_SEQ_IRQHandler();
}

void RADIO_RRM_IRQHandler(void)
{
    HAL_RADIO_RRM_IRQHandler();
}
