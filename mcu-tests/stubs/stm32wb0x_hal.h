/* Host-test stub for the STM32WB0x HAL — just enough for fpga_spi.c.
 *
 * The point is to compile the REAL Core/Src/fpga_spi.c, not a reimplementation,
 * so the bit-bang layer (bit order, 16-bit framing, NSS) is exercised too and
 * cannot drift away from what the tests claim.
 *
 * GPIO is modelled at the register level: BSRR writes and IDR reads land in
 * fake_gpio structs. __NOP() is the hook that lets the FPGA model observe the
 * pins — fpga_spi.c calls it right after every SCK_HIGH(), which is exactly the
 * sampling instant. The model is edge-triggered, so the padding NOPs around the
 * frame are harmless.
 */
#ifndef HOST_STM32WB0X_HAL_H
#define HOST_STM32WB0X_HAL_H

#include <stdint.h>

typedef struct {
    volatile uint32_t BSRR;
    volatile uint32_t IDR;
} fake_gpio_t;

extern fake_gpio_t fake_gpioa;
extern fake_gpio_t fake_gpiob;

#define GPIOA (&fake_gpioa)
#define GPIOB (&fake_gpiob)

#define GPIO_PIN_3   (1U << 3)
#define GPIO_PIN_8   (1U << 8)
#define GPIO_PIN_9   (1U << 9)
#define GPIO_PIN_11  (1U << 11)

#define GPIO_MODE_OUTPUT_PP   0U
#define GPIO_MODE_INPUT       1U
#define GPIO_NOPULL           0U
#define GPIO_SPEED_FREQ_HIGH  3U

typedef struct {
    uint32_t Pin, Mode, Pull, Speed;
} GPIO_InitTypeDef;

static inline void HAL_GPIO_Init(fake_gpio_t *port, GPIO_InitTypeDef *init)
{
    (void)port; (void)init;
}

#define __HAL_RCC_GPIOA_CLK_ENABLE()  ((void)0)
#define __HAL_RCC_GPIOB_CLK_ENABLE()  ((void)0)

/* The FPGA model's clock hook. Defined in test_fpga_spi.c. */
void fpga_model_tick(void);
#define __NOP()  fpga_model_tick()

#endif /* HOST_STM32WB0X_HAL_H */
