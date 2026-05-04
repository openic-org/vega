/*
 * stm32wb0x_it.c — interrupt service routines for the Vega WB09KE bridge.
 *
 * Identical to the reference DataThroughput client except that USART1_IRQHandler
 * also drains the TX ring buffer on TXE interrupts.  The TXE interrupt is enabled
 * by VEGA_UART_Write() and disabled here when the buffer runs empty, so the ISR
 * never fires when there is nothing to send.
 */

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

    /* RX: forward to usart_if callback (used by BLE debug traces) */
    if (LL_USART_IsActiveFlag_RXNE(USART1)) {
        uint8_t data = LL_USART_ReceiveData8(USART1);
        UartRxCpltCallback(&data, 1);
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
