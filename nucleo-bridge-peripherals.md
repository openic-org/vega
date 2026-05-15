# WB09KE Bridge — Peripheral Reference

**Board**: NUCLEO-WB09KE · STM32WB09TEFX · Cortex-M0+ · 64 KB SRAM · 512 KB Flash · BLE 5.4
**Role**: BLE Central (scanner + initiator) → USB CDC ACM bridge for the PC app

This document covers only settings that differ from the Kuntur MCU reference
(`kuntur-peripherals.md`), plus bridge-specific peripherals. The chip is identical
(STM32WB09TEFX), so all base addresses are the same.

---

## Differences from Kuntur MCU at a glance

| Item | Kuntur MCU | WB09KE Bridge |
|---|---|---|
| SYSCLK | **64 MHz** (RC64MPLL/DIV1) | **32 MHz** (RC64MPLL/DIV2) |
| Flash wait states | 1 | 0 |
| USART1 baud rate | 115 200 | **2 000 000** |
| USART1 oversampling | OVS16 | **OVS8** |
| RTC | Yes (LSE, AsynchPrediv=0) | **No** |
| FPGA SPI interface | Yes (bit-bang GPIO) | **No** |
| BLE role | Peripheral (advertiser) | **Central** (scanner) |
| LPM (DEEPSTOP) | Enabled, gated by streaming | **Disabled** (CFG_LPM_SUPPORTED=0) |
| Bonding | Enabled (mode=1) | **Disabled** (mode=0) |
| GATT server | Yes (service 0xFFF0) | **No** (GATT client only) |
| Startup delay | HAL_Delay(5000) for SWD | **None** |
| Debug printf | Blocking HAL_UART_Transmit | **Non-blocking VEGA_UART_Write** |

---

## Memory map

Identical to Kuntur MCU — same chip.

| Region | Base address | Size | Contents |
|---|---|---|---|
| Flash | `0x10040000` | 512 KB | Code + const |
| SRAM | `0x20000000` | 64 KB | Stack, heap, BLE DYN, VEGA_UART ring buffer |
| APB0 peripherals | `0x40000000` | — | SYSCFG, Flash ctrl, TIM2 (unused), RTC (unused) |
| APB1 peripherals | `0x41000000` | — | USART1 |
| AHB peripherals | `0x48000000` | — | GPIOA/B, PKA, RCC, PWR, RNG |
| APB2 / RF subsystem | `0x60000000` | — | RADIO (BLUE), WAKEUP timer |

> APB1 gating applies here too. USART1 TX is driven through the non-blocking
> VEGA_UART ring buffer from main context, so TXE interrupts never race with the
> BLE ISR — the ISR only writes BRR registers or FIFO; the BLE radio ISR gates the
> *clock*, stalling any *in-flight* APB1 access. VEGA_UART_Write enqueues into
> SRAM and enables TXE interrupt; the ISR runs whenever APB1 is accessible.

---

## 1 · RCC — Reset and Clock Control (`0x48400000`)

| Setting | Value | Notes |
|---|---|---|
| SYSCLK source | RC64MPLL | Internal PLL at 64 MHz |
| SYSCLK divider | **DIV2** | → SYSCLK = **32 MHz** |
| HSE (RF) | ON, 32 MHz | Dedicated to BLE radio; independent of SYSCLK |
| LSE | **OFF** | No RTC on this board |
| SMPS clock | RC64MPLL / DIV4 | = 16 MHz, derived before SYSCLK divider |
| GPIOA / GPIOB clocks | enabled | |
| USART1 clock | enabled | |
| RADIO clock | enabled | |

---

## 2 · Flash (`0x40001000`, code at `0x10040000`)

| Register | Field | Value | Meaning |
|---|---|---|---|
| `FLASH->ACR` | wait states | **0** | Sufficient at 32 MHz (`FLASH_WAIT_STATES_0`) |

---

## 3 · PWR — Power control (`0x48500000`)

| Setting | Value | Notes |
|---|---|---|
| `CFG_LPM_SUPPORTED` | **0** | DEEPSTOP disabled; CPU never enters sleep |
| `PWR->DBGR DEEPSTOP2` | — | Not set (no sleep) |

LPM is permanently disabled so the BLE scanner runs continuously without the
latency overhead of waking from DEEPSTOP on each scan interval.

---

## 4 · USART1 — PC link UART (`0x41004000`)

Runs at 2 Mbaud with OVS8 (OVER8=1) to match the PC app's `serial_reader.py`
(`BAUD_RATE = 2_000_000`). OVS8 allows baud rates above 32 MHz/16 = 2 Mbaud
at this SYSCLK.

| Setting | Value |
|---|---|
| Baud rate | **2 000 000** baud |
| `BRR` register | **0x0020** (= 32) → actual 2 000 000 baud, error = 0 % |
| Computation | `BRR = 2 × PCLK / baud = 2 × 32 MHz / 2 MHz = 32` |
| Word length | 8 bits |
| Stop bits | 1 |
| Parity | None |
| Mode | TX only (bridge sends, never receives PC commands) |
| HW flow control | None |
| Oversampling | **8× (`OVER8` = 1)** |
| TX pin | **PA1** — AF2 (`GPIO_AF2_USART1`), PP, no pull, low speed |
| RX pin | **PB0** — AF0 (`GPIO_AF0_USART1`) — wired but unused |

TX is driven non-blocking via VEGA_UART (Section 5). There is no blocking
`HAL_UART_Transmit` call anywhere in the bridge firmware.

---

## 5 · VEGA_UART — Non-blocking TX ring buffer (software peripheral)

Implemented in `Core/Src/vega_uart.c`. Wraps USART1 TX with a ring buffer
so BLE callbacks never block waiting for UART drain time.

| Parameter | Value |
|---|---|
| Buffer size | **4 096 bytes** (power of 2, enables bitmask wraparound) |
| Write function | `VEGA_UART_Write(const uint8_t *data, uint16_t len)` |
| ISR | `USART1_IRQHandler` → `VEGA_UART_ISR_TXE()` |
| ISR trigger | USART1 TXE (transmit data register empty) |
| ISR action | Dequeue one byte → write to `USART1->TDR`; if buffer empty, disable TXE interrupt |
| Overflow policy | Silent drop (caller gets no error; BLE packet lost if UART is too slow) |

At 2 Mbaud the UART can sustain 250 KB/s raw. The BLE side delivers at most
~125 KB/s (1 Mbps ÷ 8 bits), so the buffer never fills under steady-state streaming.
The 4 096-byte buffer absorbs any BLE burst while the UART drains.

Frame output over USART1 (one frame per BLE notification received):

```
[0xAA][0x55][len_lo][len_hi][244 bytes of StreamDataPacket_t]
```

`len` = 244 (little-endian uint16). Total frame = **248 bytes**.

---

## 6 · GPIO

| Pin | Function | Mode | Pull | Speed | AF |
|---|---|---|---|---|---|
| PA1 | USART1 TX | AF PP | None | Low | AF2 |
| PA2 | SWDIO | AF PP | Pullup | Low | AF7 |
| PB0 | USART1 RX | AF PP | None | Low | AF0 |

No bit-bang SPI pins — the bridge has no FPGA interface.

---

## 7 · RNG — Random number generator (`0x48600000`)

Same as Kuntur MCU. `HAL_RNG_Init()` enables it; used exclusively by the BLE stack.

---

## 8 · PKA — Public key accelerator (`0x48300000`)

Same as Kuntur MCU. `HAL_PKA_Init()` enables it; used by BLE Secure Connections.

ISR: `PKA_IRQHandler` → `HAL_PKA_IRQHandler(&hpka)`.

---

## 9 · RADIO / BLUE — BLE radio (`0x60000000`)

| Setting | Value | Notes |
|---|---|---|
| Clock | 32 MHz HSE RF | Dedicated oscillator, independent of SYSCLK |
| TX power | **0x18 = 0 dBm** | `CFG_TX_POWER = 0x18` (same as Kuntur) |
| BD address type | Static random | `HCI_ADDR_STATIC_RANDOM_ADDR` |
| Role | **Central** | Scanner + connection initiator |

Same five radio ISRs as Kuntur MCU (NVIC priority 0, gate APB1 clocks):
`RADIO_TXRX`, `RADIO_TXRX_SEQ`, `RADIO_RRM`, `RADIO_TIMER_CPU_WKUP`, `RADIO_TIMER_ERROR`.

---

## 10 · WAKEUP / RADIO_TIMER — Virtual timer (`0x60001800`)

| Setting | Value |
|---|---|
| `XTAL_StartupTime` | 320 |
| `enableInitialCalibration` | FALSE |
| `periodicCalibrationInterval` | 0 |

No application VTIMER on the bridge — scan and connection events are driven
purely by the BLE stack scheduler.

---

## 11 · BLE stack configuration — Central role

Defined in `Core/Inc/app_conf.h`.

| Parameter | Value | Notes |
|---|---|---|
| `CFG_BLE_ATT_MTU_MAX` | **247** | Matches Kuntur MTU |
| `CFG_BLE_NUM_GATT_ATTRIBUTES` | **0** | No GATT server on the bridge |
| `CFG_BLE_MBLOCK_COUNT_MARGIN` | **36** | Smaller pool — bridge only receives, doesn't serve |
| `CFG_BLE_ISR0_FIFO_SIZE` | 256 bytes | Critical controller events |
| `CFG_BLE_ISR1_FIFO_SIZE` | **512 bytes** | Non-critical events (larger for incoming notify bursts) |
| `CFG_BLE_USER_FIFO_SIZE` | **2 600 bytes** | Larger host FIFO for incoming BLE notification data |
| `CFG_BONDING_MODE` | **0** | No bonding — avoids filter-accept-list blocking |
| `CFG_SC_SUPPORT` | `GAP_SC_NOT_SUPPORTED` | Secure Connections disabled |
| `CFG_LPM_SUPPORTED` | **0** | No DEEPSTOP |
| DLE | **enabled** | Initiates DLE exchange (TxOctets=251, TxTime=2120) after MTU |
| 2M PHY | **enabled** | Requests 2M PHY after DLE symmetric event |
| Scan | **Passive, 1M PHY** | window=500 ms, interval=500 ms |
| Privacy | disabled | |
| `CFG_DEBUG_APP_TRACE` | **0** | `DT_INFO_MSG` logging disabled |

### Scan parameters

| Parameter | Raw value | Actual |
|---|---|---|
| Scan window | `0x0320` | 800 × 0.625 ms = **500 ms** |
| Scan interval | `0x0320` | 800 × 0.625 ms = **500 ms** (100% duty cycle) |
| PHY | 1M | Kuntur advertises at 1M |
| Mode | Passive | No SCAN_REQ sent |

100% duty cycle (window = interval) guarantees the bridge catches the first
advertisement even from Kuntur's 80–100 ms fast-advertising interval.

### Connection parameters (sent in `aci_gap_create_connection`)

| Parameter | Raw value | Actual |
|---|---|---|
| Connection interval min | `0x0006` | 6 × 1.25 ms = **7.5 ms** |
| Connection interval max | `0x0006` | 6 × 1.25 ms = **7.5 ms** |
| Peripheral latency | 0 | No latency — peripheral sends every CI |
| Supervision timeout | `0x01F4` | 500 × 10 ms = **5 000 ms** |

### GATT discovery sequence (after connect)

```
connect
  └─ aci_gatt_clt_exchange_config (MTU 247)
       └─ MTU response → hci_le_set_data_length_api (TxOctets=251 TxTime=2120)
            └─ DATA_LENGTH_CHANGE (symmetric 251) → hci_le_set_phy (TX=2M RX=2M)
                 └─ PHY UPDATE (1M or 2M accepted) → aci_gatt_clt_disc_all_primary_services
                      └─ service discovery → char discovery → descriptor discovery
                           └─ Write CCCD 0x0001 on characteristic 0xFFF2
                                └─ Kuntur MCU starts streaming
```

---

## 12 · SysTick

| Setting | Value |
|---|---|
| Reload value | 31 999 (= 32 MHz / 1000 − 1) |
| Use | `HAL_Delay()`, `HAL_GetTick()` only |

---

## CubeMX regeneration checklist

| File | Field | Required value |
|---|---|---|
| `Core/Src/main.c` | `RCC_ClkInitStruct.SYSCLKDivider` | `RCC_RC64MPLL_DIV2` |
| `Core/Src/main.c` | `HAL_RCC_ClockConfig(…)` wait states | `FLASH_WAIT_STATES_0` |
| `Core/Inc/app_conf.h` | `CFG_BONDING_MODE` | **0** |
| `Core/Inc/app_conf.h` | `CFG_LPM_SUPPORTED` | **0** |
| `Core/Inc/app_conf.h` | `CFG_BLE_NUM_GATT_ATTRIBUTES` | **0** |
| `Core/Inc/app_conf.h` | `CFG_BLE_CONTROLLER_DATA_LENGTH_EXTENSION_ENABLED` | **1** |
| `Core/Inc/app_conf.h` | `CFG_BLE_USER_FIFO_SIZE` | **2600** |
