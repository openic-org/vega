/*
 * main.c — Vega WB09KE BLE-to-UART bridge entry point.
 *
 * Identical to the reference DataThroughput client except:
 *   • USART1 baud rate set to 2 000 000 (2 Mbaud) — 30 kSPS×59 pairs×~4 B/pair
 *     generates ~126 KB/s; 115 200 baud is insufficient even for 4 kSPS.
 *   • __io_putchar routes through the interrupt-driven VEGA_UART ring buffer
 *     instead of busy-polling TXE; printf/DT_INFO_MSG never block the BLE task.
 */

#include "main.h"
#include "stm32wb0x_ll_usart.h"
#include "vega_uart.h"

PKA_HandleTypeDef  hpka;
UART_HandleTypeDef huart1;

void SystemClock_Config(void);
void PeriphCommonClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_RADIO_Init(void);
static void MX_RADIO_TIMER_Init(void);
static void MX_PKA_Init(void);
static void MX_USART1_UART_Init(void);

int main(void)
{
    HAL_Init();
    SystemClock_Config();
    PeriphCommonClock_Config();

    MX_GPIO_Init();
    MX_RADIO_Init();
    MX_RADIO_TIMER_Init();
    MX_PKA_Init();
    MX_USART1_UART_Init();
    VEGA_UART_Init();

    MX_APPE_Init(NULL);

    while (1)
    {
        MX_APPE_Process();
    }
}

void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE | RCC_OSCILLATORTYPE_LSE;
    RCC_OscInitStruct.HSEState       = RCC_HSE_ON;
    RCC_OscInitStruct.LSEState       = RCC_LSE_ON;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
        Error_Handler();

    RCC_ClkInitStruct.SYSCLKSource  = RCC_SYSCLKSOURCE_RC64MPLL;
    RCC_ClkInitStruct.SYSCLKDivider = RCC_RC64MPLL_DIV2;
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_WAIT_STATES_0) != HAL_OK)
        Error_Handler();
}

void PeriphCommonClock_Config(void)
{
    RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
    PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_SMPS;
    PeriphClkInitStruct.SmpsDivSelection     = RCC_SMPSCLK_DIV4;
    if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK)
        Error_Handler();
}

static void MX_PKA_Init(void)
{
    hpka.Instance = PKA;
    if (HAL_PKA_Init(&hpka) != HAL_OK)
        Error_Handler();
}

static void MX_RADIO_Init(void)
{
    RADIO_HandleTypeDef hradio = {0};

    if (__HAL_RCC_RADIO_IS_CLK_DISABLED()) {
        __HAL_RCC_RADIO_FORCE_RESET();
        __HAL_RCC_RADIO_RELEASE_RESET();
        __HAL_RCC_RADIO_CLK_ENABLE();
    }
    hradio.Instance = RADIO;
    HAL_RADIO_Init(&hradio);
}

static void MX_RADIO_TIMER_Init(void)
{
    RADIO_TIMER_InitTypeDef RADIO_TIMER_InitStruct = {0};

    if (__HAL_RCC_RADIO_IS_CLK_DISABLED()) {
        __HAL_RCC_RADIO_FORCE_RESET();
        __HAL_RCC_RADIO_RELEASE_RESET();
        __HAL_RCC_RADIO_CLK_ENABLE();
    }
    while (LL_RADIO_TIMER_GetAbsoluteTime(WAKEUP) < 0x10);
    RADIO_TIMER_InitStruct.XTAL_StartupTime          = 320;
    RADIO_TIMER_InitStruct.enableInitialCalibration  = FALSE;
    RADIO_TIMER_InitStruct.periodicCalibrationInterval = 0;
    HAL_RADIO_TIMER_Init(&RADIO_TIMER_InitStruct);
}

static void MX_GPIO_Init(void)
{
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    RT_DEBUG_GPIO_Init();
}

static void MX_USART1_UART_Init(void)
{
    huart1.Instance        = USART1;
    huart1.Init.BaudRate   = 2000000;   /* 2 Mbaud — required for 30 kSPS throughput */
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits   = UART_STOPBITS_1;
    huart1.Init.Parity     = UART_PARITY_NONE;
    huart1.Init.Mode       = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl  = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling    = UART_OVERSAMPLING_8;  /* OVS16 needs BRR≥16; at 16MHz APB+2Mbaud BRR=8<16 → HAL_ERROR */
    huart1.Init.OneBitSampling  = UART_ONE_BIT_SAMPLE_DISABLE;
    if (HAL_UART_Init(&huart1) != HAL_OK)
        Error_Handler();
}

/* Route printf through the non-blocking TX ring buffer. */
int __io_putchar(int ch)
{
    uint8_t b = (uint8_t)ch;
    VEGA_UART_Write(&b, 1U);
    return ch;
}

void Error_Handler(void)
{
    __disable_irq();
    while (1) {}
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    Error_Handler();
}
#endif
