# Kuntur MCU — Peripheral Reference

**Device**: STM32WB09TEFX · Cortex-M0+ · 64 KB SRAM · 512 KB Flash · BLE 5.4

---

## Memory map

| Region | Base address | Size | Contents |
|---|---|---|---|
| Flash | `0x10040000` | 512 KB | Code + const |
| SRAM | `0x20000000` | 64 KB | Stack, heap, BLE DYN |
| APB0 peripherals | `0x40000000` | — | SYSCFG, Flash ctrl, TIM2, RTC |
| APB1 peripherals | `0x41000000` | — | USART1, SPI3 (unused) |
| AHB peripherals | `0x48000000` | — | GPIOA/B, PKA, RCC, PWR, RNG |
| APB2 / RF subsystem | `0x60000000` | — | RADIO (BLUE), WAKEUP timer |

> **APB1 gating**: the BLE radio ISR (NVIC priority 0) gates all APB1 clocks during
> radio windows. Any load/store to an APB1 register while gated stalls the AHB bus
> indefinitely on Cortex-M0+. APB0 and AHB are never gated. All time-critical code
> (bit-bang SPI, ISRs) uses only APB0/AHB peripherals.

---

## 1 · RCC — Reset and Clock Control (`0x48400000`)

| Setting | Value | Notes |
|---|---|---|
| SYSCLK source | RC64MPLL | Internal PLL at 64 MHz |
| SYSCLK divider | DIV1 | → SYSCLK = **64 MHz** |
| HSE (RF) | ON, 32 MHz | Dedicated to BLE radio; independent of SYSCLK |
| LSE | ON, 32.768 kHz | Feeds RTC |
| SMPS clock | RC64MPLL / DIV4 | = **16 MHz**, derived before SYSCLK divider |
| GPIOA / GPIOB clocks | enabled | `__HAL_RCC_GPIOx_CLK_ENABLE()` |
| USART1 clock | enabled | `__HAL_RCC_USART1_CLK_ENABLE()` in MSP |
| RADIO clock | enabled | `__HAL_RCC_RADIO_CLK_ENABLE()` |

---

## 2 · Flash (`0x40001000`, code at `0x10040000`)

| Register | Field | Value | Meaning |
|---|---|---|---|
| `FLASH->ACR` | wait states | **1** | Required at 64 MHz (`FLASH_WAIT_STATES_1`) |

> At ≤32 MHz the original setting was `FLASH_WAIT_STATES_0`. Bumping to DIV1 without
> also setting wait state 1 causes random instruction fetch faults.

---

## 3 · PWR — Power control (`0x48500000`)

| Register | Field | Bit | Value | Notes |
|---|---|---|---|---|
| `PWR->DBGR` | `DEEPSTOP2` | 0 | **1** | Keeps debug subsystem alive across DEEPSTOP (DEBUG builds only) |
| — | `HAL_PWREx_EnableDBGRetention()` | — | — | Retains SWD GPIO pins on wake-up |
| LPM | `CFG_LPM_SUPPORTED` | — | 1 | DEEPSTOP allowed; gated by `CFG_LPM_FPGA_SPI` while streaming |

---

## 4 · RTC — Real-time clock (`0x40004000`)

Clock source: LSE 32.768 kHz.

| Register | Field | Bits | Value | Meaning |
|---|---|---|---|---|
| `RTC->PRER` | `PREDIV_A` | 22:16 | **0** | Async prescaler = 0 → f_ck_apre = 32 768 Hz |
| `RTC->PRER` | `PREDIV_S` | 14:0 | **32767 = 0x7FFF** | Sync prescaler → f_ck_spre = 1 Hz (calendar tick) |
| `RTC->PRER` | full word | — | **0x00007FFF** | |
| `RTC->CR` | `BYPSHAD` | 5 | **1 (0x20)** | Direct register reads — no RSF wait (`SET_BIT(hrtc.Instance->CR, RTC_CR_BYPSHAD)`) |
| `RTC->CR` | `HOUR_FORMAT` | 6 | **0** | 24-hour format |
| `RTC->TR` | H / M / S | — | 0x00 / 0x00 / 0x00 | Reset to 00:00:00 on every boot |
| `RTC->SSR` | sub-seconds | 14:0 | counts down 32767 → 0 | Resolution: 1/32768 s ≈ **30.5 µs** |

> **CubeMX warning**: if CubeMX regenerates code it resets `AsynchPrediv` to 127 and
> `SynchPrediv` to 255 (256 Hz / 3.9 ms resolution). Restore manually to 0 / 32767.

Sub-second decode used in firmware and PC app:
```
timestamp_sub_s = (32767 − SSR) × 32000 / 32768    →  0 .. 31 999
timestamp_us    = timestamp_s × 1 000 000 + timestamp_sub_s × 1000 / 32
```

---

## 5 · USART1 — Debug UART (`0x41004000`)

On APB1 — gated by BLE radio during radio windows. Only called from cooperative
scheduler task context, never from an ISR.

| Setting | Value |
|---|---|
| Baud rate | **115 200** baud |
| `BRR` register | **0x022B** (= 555) → actual 115 315 baud, error < 0.1 % |
| Word length | 8 bits |
| Stop bits | 1 |
| Parity | None |
| Mode | TX + RX |
| HW flow control | None |
| Oversampling | 16× (`OVER8` = 0) |
| One-bit sampling | Disabled |
| Clock prescaler | DIV1 |
| FIFO mode | Disabled |
| TX FIFO threshold | 1/8 |
| RX FIFO threshold | 1/8 |
| TX pin | **PA1** — AF2 (`GPIO_AF2_USART1`), PP, no pull, low speed |
| RX pin | **PB0** — AF0 (`GPIO_AF0_USART1`), PP, no pull, low speed |

---

## 6 · GPIO

GPIOA (`0x48000000`) and GPIOB (`0x48100000`) are on the AHB bus —
**never gated by the BLE radio**.

| Pin | Function | Mode | Pull | Speed | AF |
|---|---|---|---|---|---|
| PA1 | USART1 TX | AF PP | None | Low | AF2 |
| PA2 | SWDIO | AF PP | Pullup | Low | AF7 |
| PA8 | FPGA MISO | Input | None | — | — |
| PA9 | FPGA NSS | Output PP (idle HIGH) | None | Low | — |
| PA11 | FPGA MOSI | Output PP | None | **High** | — |
| PB0 | USART1 RX | AF PP | None | Low | AF0 |
| PB3 | FPGA SCK | Output PP (idle LOW) | None | **High** | — |

> `FPGA_SPI_Init()` runs after `MX_GPIO_Init()` and overwrites the CubeMX-generated
> SPI3 alternate-function settings on PB3, PA8, and PA11.

GPIO BSRR access pattern used by bit-bang SPI:

| Operation | Register write |
|---|---|
| SCK HIGH | `GPIOB->BSRR = GPIO_PIN_3` |
| SCK LOW | `GPIOB->BSRR = GPIO_PIN_3 << 16` |
| MOSI HIGH | `GPIOA->BSRR = GPIO_PIN_11` |
| MOSI LOW | `GPIOA->BSRR = GPIO_PIN_11 << 16` |
| NSS LOW (assert) | `GPIOA->BSRR = GPIO_PIN_9 << 16` |
| NSS HIGH (deassert) | `GPIOA->BSRR = GPIO_PIN_9` |
| MISO read | `(GPIOA->IDR >> 8) & 1` (PA8 = bit 8) |

---

## 7 · Bit-bang SPI — FPGA interface (software peripheral)

Not a hardware peripheral. Implemented in `Core/Src/fpga_spi.c` using GPIOA/GPIOB
BSRR writes. Compiled with `__attribute__((optimize("O2")))` — fully unrolled, no
loop counter or variable shift.

| Setting | Value |
|---|---|
| SPI mode | Mode 0 (CPOL=0, CPHA=0) |
| Bit order | MSB first |
| Word width | 16 bits |
| TX command word | `FPGA_STREAM_CMD = 0xA5A5` (FPGA ignores TX content) |
| Transfer time | ~2.5 µs @ 64 MHz (GCC -O2, 16-bit fully unrolled) |
| Effective SCK frequency | ~2 MHz |
| NSS | PA9, active LOW, asserted per-transfer inside `spi_bb_transfer()` |
| Pairs per BLE packet | 59 (`STREAM_PAIRS_PER_PACKET`) = 119 SPI calls total (1 cmd + 118 data) |
| Total SPI time per packet | ~298 µs @ 64 MHz |

---

## 8 · RNG — Random number generator (`0x48600000`)

No explicit register configuration. `HAL_RNG_Init()` enables the clock and peripheral.
Used exclusively by the BLE stack for session key generation and encryption nonces.

---

## 9 · PKA — Public key accelerator (`0x48300000`)

No explicit register configuration. `HAL_PKA_Init()` enables it. Used by the BLE
stack for Secure Connections (ECDH key exchange during pairing).

ISR: `PKA_IRQHandler` → `HAL_PKA_IRQHandler(&hpka)`.

---

## 10 · RADIO / BLUE — BLE radio (`0x60000000`)

| Setting | Value | Notes |
|---|---|---|
| Clock | 32 MHz HSE RF | Dedicated oscillator, **independent of SYSCLK** |
| TX power | **0x18 = 0 dBm** | `CFG_TX_POWER = 0x18` |
| BD address type | Static random | `HCI_ADDR_STATIC_RANDOM_ADDR` |
| Device name | `Kuntur-Headstage` | Matched by WB09KE bridge scan filter |

Active ISRs (NVIC priority 0 — highest, gates APB1 clocks):

| Handler | Role |
|---|---|
| `RADIO_TXRX_IRQHandler` | Main radio TX/RX event |
| `RADIO_TXRX_SEQ_IRQHandler` | Sequencer event |
| `RADIO_RRM_IRQHandler` | Radio resource manager |
| `RADIO_TIMER_CPU_WKUP_IRQHandler` | CPU wake-up from radio timer |
| `RADIO_TIMER_ERROR_IRQHandler` | Radio timer error |

---

## 11 · WAKEUP / RADIO_TIMER — Virtual timer (`0x60001800`)

| Setting | Value |
|---|---|
| `XTAL_StartupTime` | 320 |
| `enableInitialCalibration` | FALSE |
| `periodicCalibrationInterval` | 0 |
| `send_timer` period | **2 ms** (`STREAM_SEND_PERIOD_MS`) — safety fallback for `StreamSendTask` |

The VTIMER infrastructure multiplexes multiple software timers onto the single
radio hardware timer. `send_timer` is a safety fallback that re-primes
`StreamSendTask` if the event-driven tight loop stalls; at full throughput the
loop re-schedules itself faster than the 2 ms period.

---

## 12 · BLE stack configuration

Defined in `Core/Inc/app_conf.h`.

| Parameter | Value | Notes |
|---|---|---|
| `CFG_BLE_ATT_MTU_MAX` | **247** | Packet payload = 244 bytes |
| `CFG_BLE_NUM_GATT_ATTRIBUTES` | **68** | Restore to 68 after any CubeMX regeneration (default = 17) |
| `CFG_BLE_MBLOCK_COUNT_MARGIN` | **54** | mblock pool for TX queue depth |
| `CFG_BLE_ISR0_FIFO_SIZE` | 256 bytes | Critical controller events (RX data) |
| `CFG_BLE_ISR1_FIFO_SIZE` | 768 bytes | Non-critical events (adv reports) |
| `CFG_BLE_USER_FIFO_SIZE` | 1024 bytes | Host / application events |
| `CFG_BLE_SLEEP_CLOCK_ACCURACY` | **100 ppm** | LSE crystal accuracy |
| `ADV_INTERVAL_MIN/MAX` | **0x0080 / 0x00A0** | = 80–100 ms fast advertising |
| `ADV_LP_INTERVAL_MIN/MAX` | **0x0640 / 0x0FA0** | = 1000–2500 ms LP advertising (after 60 s) |
| `CFG_BONDING_MODE` | **1** | Bonding enabled |
| `CFG_SC_SUPPORT` | `GAP_SC_OPTIONAL` | Secure Connections optional |
| DLE | **enabled** | `CFG_BLE_CONTROLLER_DATA_LENGTH_EXTENSION_ENABLED = 1`; restore after CubeMX regeneration (default = 0) |
| 2M PHY | **enabled** | `CFG_BLE_CONTROLLER_2M_CODED_PHY_ENABLED = 1` |
| Scan | disabled | Peripheral only |
| Privacy | disabled | |

---

## 13 · SysTick

Configured by `HAL_Init()` at **1 ms** intervals.

| Setting | Value |
|---|---|
| Reload value | 63 999 (= 64 MHz / 1000 − 1) |
| Use | `HAL_Delay()`, `HAL_GetTick()` only |

Not used by the BLE stack or the streaming data path.

---

## CubeMX regeneration checklist

If CubeMX regenerates any file, manually restore these values before building:

| File | Field | Required value |
|---|---|---|
| `Core/Src/main.c` | `hrtc.Init.AsynchPrediv` | **0** |
| `Core/Src/main.c` | `hrtc.Init.SynchPrediv` | **32767** |
| `Core/Src/main.c` | `RCC_ClkInitStruct.SYSCLKDivider` | `RCC_RC64MPLL_DIV1` |
| `Core/Src/main.c` | `HAL_RCC_ClockConfig(…)` wait states | `FLASH_WAIT_STATES_1` |
| `Core/Inc/app_conf.h` | `CFG_BLE_NUM_GATT_ATTRIBUTES` | **68** |
| `Core/Inc/app_conf.h` | `CFG_BLE_CONTROLLER_DATA_LENGTH_EXTENSION_ENABLED` | **1** |
