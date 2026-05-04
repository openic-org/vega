# Vega WB09KE BLE-to-UART bridge
#
# Bridge-specific sources live here; all boilerplate (HAL, BLE middleware,
# system init, usart_if) is shared from the reference DataThroughput client.
#
# V1.4.0 supplies Drivers/ and Utilities/ (not present in V1.4.1)
# V1.4.1 supplies updated Middlewares/ and Projects/
CUBE_DRV_ROOT ?= /home/manuel/STM32Cube/Repository/STM32Cube_FW_WB0_V1.4.0
CUBE_MW_ROOT  ?= /home/manuel/STM32Cube/Repository/STM32Cube_FW_WB0_V1.4.1
CUBE_PROJECTS ?= $(CUBE_MW_ROOT)/Projects

# Reference DataThroughput client — shared boilerplate
CLIENT := ../../stm32ble-test/client

TARGET    := Vega_Bridge
BUILD_DIR := build

TOOLCHAIN_PATH ?= /opt/st/stm32cubeide_2.1.1/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.linux64_1.0.100.202602081740/tools/bin
PREFIX := arm-none-eabi-
CC     := $(TOOLCHAIN_PATH)/$(PREFIX)gcc
AS     := $(TOOLCHAIN_PATH)/$(PREFIX)gcc -x assembler-with-cpp
CP     := $(TOOLCHAIN_PATH)/$(PREFIX)objcopy
SZ     := $(TOOLCHAIN_PATH)/$(PREFIX)size

CPU := -mcpu=cortex-m0plus -mthumb -mfloat-abi=soft

DEBUG ?= 0
ifeq ($(DEBUG),1)
OPT := -Og -g3 -DDEBUG
else
OPT := -Os
endif

DEFS := \
  -DCUSTOM_WB09TE \
  -DUSE_FULL_LL_DRIVER \
  -DUSE_HAL_DRIVER \
  -DSTM32WB09

# ── C sources ────────────────────────────────────────────────────────────────
# Bridge-specific (local)
C_SOURCES := \
  Core/Src/main.c \
  Core/Src/stm32wb0x_it.c \
  STM32_BLE/App/app_ble.c \
  STM32_BLE/App/vega_bridge_app.c \
  STM32_BLE/App/vega_uart.c \

# Boilerplate shared from reference client
C_SOURCES += \
  $(CLIENT)/Core/Src/app_entry.c \
  $(CLIENT)/Core/Src/stm32wb0x_hal_msp.c \
  $(CLIENT)/Core/Src/system_stm32wb0x.c \
  $(CLIENT)/STM32_BLE/Target/blenvm.c \
  $(CLIENT)/STM32_BLE/Target/bleplat.c \
  $(CLIENT)/STM32_BLE/Target/bleplat_cntr.c \
  $(CLIENT)/System/Config/Debug_GPIO/app_debug.c \
  $(CLIENT)/System/Interfaces/usart_if.c \
  $(CLIENT)/STM32CubeIDE/Application/User/Core/syscalls.c \
  $(CLIENT)/STM32CubeIDE/Application/User/Core/sysmem.c \

# STM32Cube HAL drivers
C_SOURCES += \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_cortex.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_dma.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_flash.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_flash_ex.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_gpio.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_pka.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_pwr.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_pwr_ex.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_radio.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_radio_timer.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_rcc.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_rcc_ex.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_rng.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_uart.c \
  $(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Src/stm32wb0x_hal_uart_ex.c \

# STM32Cube BLE middleware
C_SOURCES += \
  $(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/evt_handler/src/ble_evt.c \
  $(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/stack/config/ble_stack_user_cfg.c \
  $(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/queued_writes/src/eatt_pwrq.c \

# Utilities
C_SOURCES += \
  $(CUBE_DRV_ROOT)/Utilities/trace/adv_trace/stm32_adv_trace.c \
  $(CUBE_DRV_ROOT)/Utilities/lpm/tiny_lpm/stm32_lpm.c \
  $(CUBE_DRV_ROOT)/Utilities/misc/stm32_mem.c \
  $(CUBE_DRV_ROOT)/Utilities/sequencer/stm32_seq.c \

# Common BLE modules
C_SOURCES += \
  $(CUBE_PROJECTS)/Common/BLE/Interfaces/cryptolib_hw_aes.c \
  $(CUBE_PROJECTS)/Common/BLE/Interfaces/hw_aes.c \
  $(CUBE_PROJECTS)/Common/BLE/Interfaces/hw_pka.c \
  $(CUBE_PROJECTS)/Common/BLE/Interfaces/hw_rng.c \
  $(CUBE_PROJECTS)/Common/BLE/Interfaces/stm32_lpm_if.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/miscutil.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/osal.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/stm_list.c \
  $(CUBE_PROJECTS)/Common/BLE/Startup/device_context_switch.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/Flash/flash_driver.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/Flash/flash_manager.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/NVMDB/Src/nvm_db.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/NVMDB/Src/nvm_db_conf.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/PKAMGR/Src/pka_manager.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/Profiles/Src/gap_profile.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/Profiles/Src/gatt_profile.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/RADIO_utils/Src/RADIO_utils.c \
  $(CUBE_PROJECTS)/Common/BLE/Modules/RTDebug/RTDebug.c \

# ── Assembly sources ──────────────────────────────────────────────────────────
ASM_SOURCES := \
  $(CLIENT)/STM32CubeIDE/Application/User/Startup/startup_stm32wb09kevx.s \
  $(CUBE_PROJECTS)/Common/BLE/Modules/blue_unit_conversion.s \
  $(CUBE_PROJECTS)/Common/BLE/Modules/osal_memcpy.s \
  ../../stm32ble-test/common/ble/cpu_context_switch.s \

# ── Include paths ─────────────────────────────────────────────────────────────
# Bridge-specific headers first so app_conf.h shadows the reference version.
INCLUDES := \
  -ICore/Inc \
  -ISTM32_BLE/App \
  -I$(CLIENT)/Core/Inc \
  -I$(CLIENT)/STM32_BLE/App \
  -I$(CLIENT)/STM32_BLE/Target \
  -I$(CLIENT)/System/Config/Debug_GPIO \
  -I$(CLIENT)/System/Interfaces \
  -I$(CUBE_DRV_ROOT)/Utilities/trace/adv_trace \
  -I$(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Inc \
  -I$(CUBE_DRV_ROOT)/Drivers/STM32WB0x_HAL_Driver/Inc/Legacy \
  -I$(CUBE_PROJECTS)/Common/BLE/Interfaces \
  -I$(CUBE_PROJECTS)/Common/BLE/Modules \
  -I$(CUBE_PROJECTS)/Common/BLE/Modules/RTDebug \
  -I$(CUBE_PROJECTS)/Common/BLE/Modules/RADIO_utils/Inc \
  -I$(CUBE_PROJECTS)/Common/BLE/Modules/Profiles/Inc \
  -I$(CUBE_PROJECTS)/Common/BLE/Modules/PKAMGR/Inc \
  -I$(CUBE_PROJECTS)/Common/BLE/Modules/NVMDB/Inc \
  -I$(CUBE_PROJECTS)/Common/BLE/Modules/Flash \
  -I$(CUBE_PROJECTS)/Common/BLE/Startup \
  -I$(CUBE_DRV_ROOT)/Utilities/misc \
  -I$(CUBE_DRV_ROOT)/Utilities/sequencer \
  -I$(CUBE_DRV_ROOT)/Utilities/lpm/tiny_lpm \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib/Inc \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib/Inc/Common \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib/Inc/AES \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib/Inc/AES/CBC \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib/Inc/AES/CMAC \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib/Inc/AES/Common \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib/Inc/AES/ECB \
  -I$(CUBE_DRV_ROOT)/Drivers/CMSIS/Device/ST/STM32WB0X/Include \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/evt_handler/inc \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/queued_writes/inc \
  -I$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/stack/include \
  -I$(CUBE_DRV_ROOT)/Drivers/CMSIS/Include \

LDSCRIPT := $(CLIENT)/STM32CubeIDE/STM32WB09KEVX_FLASH.ld

LDLIBS := \
  -L$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/cryptolib \
  -L$(CUBE_MW_ROOT)/Middlewares/ST/STM32_BLE/stack/lib \
  -Wl,--start-group \
  -l:libcrypto.a \
  -l:stm32wb0x_ble_stack.a \
  -Wl,--end-group \

CFLAGS  := $(CPU) $(OPT) $(DEFS) $(INCLUDES) \
           -ffunction-sections -fdata-sections -fstack-usage \
           --specs=nano.specs
ASFLAGS := $(CPU) $(OPT) -ffunction-sections -fdata-sections \
           -I$(CUBE_PROJECTS)/Common/BLE/Modules \
           -I../../stm32ble-test/common/ble
LDFLAGS := $(CPU) --specs=nano.specs --specs=nosys.specs \
           -T$(LDSCRIPT) \
           -Wl,--gc-sections \
           -Wl,-Map=$(BUILD_DIR)/$(TARGET).map \
           -Wl,-z,noexecstack \
           -Wl,--print-memory-usage

OBJECTS  := $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))
OBJECTS  += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))
vpath %.c $(sort $(dir $(C_SOURCES)))
vpath %.s $(sort $(dir $(ASM_SOURCES)))

.PHONY: all clean flash

all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).bin $(BUILD_DIR)/$(TARGET).hex

# Explicit rules for bridge files whose basenames shadow reference files.
# Make gives explicit rules priority over vpath-resolved pattern rules.
$(BUILD_DIR)/main.o: Core/Src/main.c | $(BUILD_DIR)
	$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/main.lst $< -o $@

$(BUILD_DIR)/stm32wb0x_it.o: Core/Src/stm32wb0x_it.c | $(BUILD_DIR)
	$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/stm32wb0x_it.lst $< -o $@

$(BUILD_DIR)/%.o: %.c | $(BUILD_DIR)
	$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/$(notdir $(<:.c=.lst)) $< -o $@

$(BUILD_DIR)/%.o: %.s | $(BUILD_DIR)
	$(AS) -c $(ASFLAGS) $< -o $@

$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS)
	$(CC) $(OBJECTS) $(LDFLAGS) $(LDLIBS) -o $@
	$(SZ) $@

$(BUILD_DIR)/$(TARGET).bin: $(BUILD_DIR)/$(TARGET).elf
	$(CP) -O binary $< $@

$(BUILD_DIR)/$(TARGET).hex: $(BUILD_DIR)/$(TARGET).elf
	$(CP) -O ihex $< $@

$(BUILD_DIR):
	mkdir -p $@

clean:
	rm -rf $(BUILD_DIR)

flash: $(BUILD_DIR)/$(TARGET).elf
	STM32_Programmer_CLI -c port=SWD freq=4000 -w $< -v -rst
