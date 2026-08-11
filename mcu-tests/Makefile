# Host verification of the Kuntur MCU's SPI0 helpers.
# Compiles the REAL fpga_spi.c against stub HAL headers and a pin-level model
# of the A.1.1g FPGA FSM — see test_fpga_spi.c for what that buys.
#
# MCU source path is per CLAUDE.md; override if the tree moves:
#   make MCU=/path/to/kuntur-mcu

MCU ?= /data/projects/kuntur/kuntur144/mcu/kuntur-mcu

CFLAGS = -std=c11 -O1 -g -Wall -Wextra -Wno-unused-parameter \
         -Istubs -I$(MCU)/Core/Inc

all: test_fpga_spi

test_fpga_spi: test_fpga_spi.c $(MCU)/Core/Src/fpga_spi.c
	$(CC) $(CFLAGS) -o $@ $^

check: test_fpga_spi
	./test_fpga_spi

clean:
	rm -f test_fpga_spi

.PHONY: all check clean
