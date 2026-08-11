/* Host verification of the Kuntur MCU's SPI0 helpers, including the new
 * register console (docs/interfaces/fpga-diagnostic-access.md §3.1).
 *
 * No ARM toolchain is available here, so the firmware .elf cannot be built.
 * What CAN be checked on the host is the part that is new and untested: the
 * command sequences fpga_spi.c puts on the wire. This compiles the REAL
 * Core/Src/fpga_spi.c against a pin-level model of the A.1.1g FPGA FSM
 * (docs/interfaces/channel-selection-control-plane.md §1), so it exercises the
 * bit-bang layer too — bit order, 16-bit framing, NSS — rather than trusting a
 * reimplementation to agree with it.
 *
 * The property this exists to protect: a REG_WRITE16 that silently never lands
 * and a genuinely wrong RTL response-delay both present as rung (b) failing on
 * the bench. This suite removes the first explanation so a bench failure means
 * what it says.
 *
 *   make -C mcu-tests && mcu-tests/test_fpga_spi
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "stm32wb0x_hal.h"   /* the stub: fake_gpio_t, __NOP() hook */
#include "fpga_spi.h"

int dbg_quiet = 1;

fake_gpio_t fake_gpioa;
fake_gpio_t fake_gpiob;

/* ── Pin decode, mirroring fpga_spi.c's wiring ──────────────────────────── */
#define SCK_BIT   (1U << 3)     /* PB3  */
#define MISO_BIT  (1U << 8)     /* PA8  */
#define MOSI_BIT  (1U << 11)    /* PA11 */
#define NSS_BIT   (1U << 9)     /* PA9  */

/* ── FPGA model: SPI0 slave + A.1.1g main_controller FSM + regbank + fifo ── */

enum { ST_DECODE, ST_WRITE1, ST_WRITE2, ST_POP1 };

static struct {
    /* pin shadow — levels, surviving the BSRR consume in fpga_model_tick() */
    int mosi, nss, prev_nss;
    /* shift registers */
    uint16_t rx_shift, tx_shift;
    int bit_count;
    /* one-transfer-deep response pipeline */
    uint16_t pending_response;
    /* FSM */
    int state;
    uint8_t addr_reg, staged_h;
    uint16_t ram[256];
    /* fifo */
    uint16_t fifo_a[512], fifo_b[512];
    int fifo_head, fifo_tail;
    /* observation */
    uint16_t seen[512];
    int seen_n;
    int aborts;
} fpga;

static void fifo_push(uint16_t a, uint16_t b)
{
    fpga.fifo_a[fpga.fifo_tail] = a;
    fpga.fifo_b[fpga.fifo_tail] = b;
    fpga.fifo_tail++;
}
static int fifo_empty(void) { return fpga.fifo_head >= fpga.fifo_tail; }

/* Process one complete 16-bit transfer: run the FSM, and compute what MISO
 * will carry on the NEXT transfer (the one-transfer-deep pipeline). */
static void fpga_process(uint16_t w)
{
    if (fpga.seen_n < (int)(sizeof fpga.seen / sizeof fpga.seen[0]))
        fpga.seen[fpga.seen_n++] = w;

    uint8_t opcode = (uint8_t)(w >> 14);
    uint8_t tag    = (uint8_t)((w >> 8) & 0x3F);
    uint8_t data   = (uint8_t)(w & 0xFF);
    uint16_t resp  = 0x0000;

    switch (fpga.state) {
    case ST_DECODE:
        if (opcode == 0x1) {                 /* REG_WRITE */
            if (tag == 1) { fpga.addr_reg = data; fpga.state = ST_WRITE1; }
            else          { fpga.aborts++; }
        } else if (opcode == 0x2) {          /* REG_READ, self-addressing */
            if (tag == 1) { fpga.addr_reg = data; resp = fpga.ram[data]; }
            else          { fpga.aborts++; }
        } else if (opcode == 0x0) {          /* FIFO_POP, first of pair */
            resp = fifo_empty() ? 0x8000 : fpga.fifo_a[fpga.fifo_head];
            fpga.state = ST_POP1;
        }                                     /* opcode 0x3 = NOP: nothing */
        break;

    case ST_WRITE1:
        if (opcode == 0x1 && tag == 2) { fpga.staged_h = data; fpga.state = ST_WRITE2; }
        else { fpga.aborts++; fpga.state = ST_DECODE; }
        break;

    case ST_WRITE2:
        if (opcode == 0x1 && tag == 3) {
            fpga.ram[fpga.addr_reg] = (uint16_t)((fpga.staged_h << 8) | data);
        } else {
            fpga.aborts++;
        }
        fpga.state = ST_DECODE;
        break;

    case ST_POP1:
        if (opcode == 0x0) {
            resp = fifo_empty() ? 0x8000 : fpga.fifo_b[fpga.fifo_head];
            if (!fifo_empty()) fpga.fifo_head++;
        } else {
            /* Broken pair: the abort consumes this transfer and costs the
             * entry whose ChA was already delivered (spec §1a, tb T7). */
            fpga.aborts++;
            if (!fifo_empty()) fpga.fifo_head++;
        }
        fpga.state = ST_DECODE;
        break;
    }

    fpga.pending_response = resp;
}

/* Called from __NOP(), which fpga_spi.c invokes twice right after every
 * SCK_HIGH() — exactly the sampling instant — plus as padding around the frame.
 *
 * BSRR is CONSUMED (zeroed) on each tick, matching the hardware: it is a
 * write-only "apply this edge and forget" register, not a level latch. That is
 * what makes this work at all — SCK_LOW() is overwritten by the next bit's
 * SCK_HIGH() before any __NOP() runs, so a level-based edge detector would see
 * SCK stuck high and count one bit per frame instead of sixteen. Pin *levels*
 * live in the shadow fields, which survive the consume. */
void fpga_model_tick(void)
{
    uint32_t a = fake_gpioa.BSRR;
    uint32_t b = fake_gpiob.BSRR;
    if (a) fake_gpioa.BSRR = 0;
    if (b) fake_gpiob.BSRR = 0;

    if (a & MOSI_BIT)         fpga.mosi = 1;
    if (a & (MOSI_BIT << 16)) fpga.mosi = 0;
    if (a & NSS_BIT)          fpga.nss = 1;
    if (a & (NSS_BIT << 16))  fpga.nss = 0;

    /* NSS falling: start of frame — latch the response computed last frame
     * (the one-transfer-deep pipeline). */
    if (fpga.prev_nss && !fpga.nss) {
        fpga.tx_shift = fpga.pending_response;
        fpga.rx_shift = 0;
        fpga.bit_count = 0;
    }

    /* A SCK_HIGH write is one rising edge: sample MOSI, present the MISO bit
     * the master will read after these NOPs. */
    if ((b & SCK_BIT) && !fpga.nss) {
        fpga.rx_shift = (uint16_t)((fpga.rx_shift << 1) | (unsigned)fpga.mosi);
        fpga.bit_count++;
        fake_gpioa.IDR = (fpga.tx_shift & 0x8000) ? MISO_BIT : 0;
        fpga.tx_shift = (uint16_t)(fpga.tx_shift << 1);
    }

    /* NSS rising: end of frame — process the word just received. */
    if (!fpga.prev_nss && fpga.nss && fpga.bit_count == 16) {
        fpga_process(fpga.rx_shift);
        fpga.bit_count = 0;
    }

    fpga.prev_nss = fpga.nss;
}

static void fpga_reset(void)
{
    memset(&fpga, 0, sizeof fpga);
    fpga.nss = fpga.prev_nss = 1;
    fpga.state = ST_DECODE;
}
static void seen_clear(void) { fpga.seen_n = 0; }

/* ── Assertions ─────────────────────────────────────────────────────────── */

static int failures, checks;

#define CHECK(cond, fmt, ...)                                              \
    do {                                                                   \
        checks++;                                                          \
        if (!(cond)) {                                                     \
            failures++;                                                    \
            printf("  FAIL %s:%d  " fmt "\n", __func__, __LINE__, ##__VA_ARGS__); \
        }                                                                  \
    } while (0)

static void check_seq(const uint16_t *want, int n, const char *what)
{
    checks++;
    int ok = (fpga.seen_n == n);
    for (int i = 0; ok && i < n; i++) ok = (fpga.seen[i] == want[i]);
    if (!ok) {
        failures++;
        printf("  FAIL %s: got %d transfers [", what, fpga.seen_n);
        for (int i = 0; i < fpga.seen_n; i++) printf("%04X ", fpga.seen[i]);
        printf("], want %d [", n);
        for (int i = 0; i < n; i++) printf("%04X ", want[i]);
        printf("]\n");
    }
}

/* Expected wire words, built from the spec rather than from fpga_spi.c's
 * private helpers — an independent encoding, so a bug in those helpers cannot
 * hide by being reused here. */
static uint16_t W(uint8_t tag, uint8_t d) { return (uint16_t)(0x4000 | (tag << 8) | d); }
static uint16_t R(uint8_t addr)           { return (uint16_t)(0x8000 | (1 << 8) | addr); }
static uint16_t NOPW(void)                { return 0xC000; }

/* ── Tests ──────────────────────────────────────────────────────────────── */

static void t_reg_write16(void)
{
    fpga_reset(); seen_clear();
    FPGA_SPI_RegWrite16(0x30, 0x95A5);
    uint16_t want[] = { W(1, 0x30), W(2, 0x95), W(3, 0xA5) };
    check_seq(want, 3, "RegWrite16 sequence");
    CHECK(fpga.ram[0x30] == 0x95A5, "ram[0x30]=%04X want 95A5", fpga.ram[0x30]);
    CHECK(fpga.state == ST_DECODE, "FSM left mid-sequence (state %d)", fpga.state);
    CHECK(fpga.aborts == 0, "%d aborts", fpga.aborts);
}

static void t_reg_read16(void)
{
    fpga_reset();
    FPGA_SPI_RegWrite16(0x31, 0x3C5A);
    seen_clear();
    uint16_t v = FPGA_SPI_RegRead16(0x31);
    uint16_t want[] = { R(0x31), NOPW() };
    check_seq(want, 2, "RegRead16 sequence");
    CHECK(v == 0x3C5A, "RegRead16 returned %04X want 3C5A", v);
    CHECK(fpga.state == ST_DECODE, "FSM not at decode");
    CHECK(fpga.aborts == 0, "%d aborts", fpga.aborts);
}

/* The 16-bit path is the whole point of A.1.1g: a staged high byte that is
 * never written reads back 0x00xx, and one stuck at its previous value reads
 * back the wrong high byte. Non-zero, distinct high bytes catch both. */
static void t_16bit_width(void)
{
    fpga_reset();
    FPGA_SPI_RegWrite16(48, 0x95A5);
    FPGA_SPI_RegWrite16(49, 0x3C5A);
    CHECK(FPGA_SPI_RegRead16(48) == 0x95A5, "word 48 lost its high byte");
    CHECK(FPGA_SPI_RegRead16(49) == 0x3C5A, "word 49 lost its high byte");
    /* Re-read 48 after writing 49 — catches a commit to a stale addr_reg. */
    CHECK(FPGA_SPI_RegRead16(48) == 0x95A5, "word 48 clobbered by the write to 49");
}

static void t_roundtrip_all_words(void)
{
    fpga_reset();
    int bad = 0;
    for (int a = 0; a < 256; a++) {
        uint16_t v = (uint16_t)(0xA000 ^ (a * 0x0101));
        FPGA_SPI_RegWrite16((uint8_t)a, v);
        if (FPGA_SPI_RegRead16((uint8_t)a) != v) bad++;
    }
    CHECK(bad == 0, "%d/256 words failed write→read round trip", bad);
    CHECK(fpga.aborts == 0, "%d aborts over 256 round trips", fpga.aborts);
}

static void t_sampling_slot(void)
{
    fpga_reset();
    CHECK(FPGA_SPI_SetSamplingSlot(0, 0xFB00) == 1, "slot 0 rejected");
    CHECK(fpga.ram[48] == 0xFB00, "slot 0 -> ram[48]=%04X", fpga.ram[48]);
    CHECK(FPGA_SPI_SetSamplingSlot(32, 0xFF00) == 1, "slot 32 rejected");
    CHECK(fpga.ram[80] == 0xFF00, "slot 32 -> ram[80]=%04X", fpga.ram[80]);

    /* Out of range must issue NO transfers — silently writing nothing is worse
     * than visibly writing nothing. */
    seen_clear();
    CHECK(FPGA_SPI_SetSamplingSlot(33, 0x1234) == 0, "slot 33 accepted");
    CHECK(fpga.seen_n == 0, "slot 33 emitted %d transfers, want 0", fpga.seen_n);
    CHECK(FPGA_SPI_SetSamplingSlot(255, 0x1234) == 0, "slot 255 accepted");
    CHECK(fpga.seen_n == 0, "slot 255 emitted %d transfers, want 0", fpga.seen_n);
}

static void t_control_words(void)
{
    fpga_reset();
    FPGA_SPI_SetChannels(0x83, 0x82);
    CHECK(fpga.ram[196] == 0x0083, "ch_a -> ram[196]=%04X", fpga.ram[196]);
    CHECK(fpga.ram[197] == 0x0082, "ch_b -> ram[197]=%04X", fpga.ram[197]);
    uint8_t ra = 0, rb = 0;
    FPGA_SPI_ReadChannels(&ra, &rb);
    CHECK(ra == 0x83 && rb == 0x82, "ReadChannels got %02X/%02X want 83/82", ra, rb);

    FPGA_SPI_SetStreamEnable(0);
    CHECK(fpga.ram[228] == 0, "stream_enable=%04X want 0", fpga.ram[228]);
    CHECK(FPGA_SPI_ReadStreamEnable() == 0, "ReadStreamEnable want 0");
    FPGA_SPI_SetStreamEnable(1);
    CHECK(fpga.ram[228] == 1, "stream_enable=%04X want 1", fpga.ram[228]);
    CHECK(FPGA_SPI_ReadStreamEnable() == 1, "ReadStreamEnable want 1");

    FPGA_SPI_SetDataSource(1);
    CHECK(fpga.ram[229] == 1, "data_source=%04X want 1", fpga.ram[229]);
    CHECK(FPGA_SPI_ReadDataSource() == 1, "ReadDataSource want 1");
    FPGA_SPI_SetDataSource(0);
    CHECK(fpga.ram[229] == 0, "data_source=%04X want 0", fpga.ram[229]);
    CHECK(FPGA_SPI_ReadDataSource() == 0, "ReadDataSource want 0");
    CHECK(fpga.aborts == 0, "%d aborts", fpga.aborts);
}

static void t_read_samples(void)
{
    fpga_reset();
    for (int i = 0; i < 8; i++) fifo_push((uint16_t)(100 + i), (uint16_t)(200 + i));
    int16_t buf[16];
    memset(buf, 0, sizeof buf);
    seen_clear();
    FPGA_SPI_ReadSamples(buf, 8);
    CHECK(fpga.seen_n == 17, "ReadSamples(8) emitted %d transfers, want 17", fpga.seen_n);
    int bad = 0;
    for (int i = 0; i < 8; i++)
        if (buf[2 * i] != (int16_t)(100 + i) || buf[2 * i + 1] != (int16_t)(200 + i)) bad++;
    CHECK(bad == 0, "%d/8 sample pairs wrong (first: %d/%d)", bad, buf[0], buf[1]);
    CHECK(fpga.state == ST_DECODE, "FIFO_POP pair left half-open");
    CHECK(fpga.aborts == 0, "%d aborts — a POP pair was broken", fpga.aborts);
}

/* The property that makes any function safe to call after any other. A dangling
 * sequence is exactly the 2026-08-11 latent failure: a half-open POP pair would
 * have eaten STOP_STREAMING's tag-1 write and streaming would never have
 * stopped. */
static void t_no_dangling_sequences(void)
{
    int16_t buf[8];

    fpga_reset();
    for (int i = 0; i < 32; i++) fifo_push((uint16_t)i, (uint16_t)(i + 1000));

    /* Interleave every public entry point in an awkward order. */
    FPGA_SPI_ReadSamples(buf, 2);
    CHECK(fpga.state == ST_DECODE, "dangling after ReadSamples");
    FPGA_SPI_RegWrite16(200, 0xBEEF);
    CHECK(fpga.state == ST_DECODE, "dangling after RegWrite16");
    FPGA_SPI_ReadSamples(buf, 1);
    CHECK(fpga.state == ST_DECODE, "dangling after ReadSamples");
    (void)FPGA_SPI_RegRead16(200);
    CHECK(fpga.state == ST_DECODE, "dangling after RegRead16");
    FPGA_SPI_SetChannels(0x03, 0x02);
    CHECK(fpga.state == ST_DECODE, "dangling after SetChannels");
    FPGA_SPI_ReadSamples(buf, 3);
    CHECK(fpga.state == ST_DECODE, "dangling after ReadSamples");
    FPGA_SPI_SetStreamEnable(0);
    CHECK(fpga.state == ST_DECODE, "dangling after SetStreamEnable");
    (void)FPGA_SPI_ReadStreamEnable();
    CHECK(fpga.state == ST_DECODE, "dangling after ReadStreamEnable");
    (void)FPGA_SPI_SetSamplingSlot(10, 0x1234);
    CHECK(fpga.state == ST_DECODE, "dangling after SetSamplingSlot");
    FPGA_SPI_SetDataSource(0);
    CHECK(fpga.state == ST_DECODE, "dangling after SetDataSource");

    CHECK(fpga.aborts == 0, "%d aborts across the interleaved sequence", fpga.aborts);
    CHECK(fpga.ram[200] == 0xBEEF, "ram[200]=%04X survived the interleave", fpga.ram[200]);
    CHECK(fpga.ram[196] == 0x0003 && fpga.ram[197] == 0x0002, "channels survived");
}

/* Friendly index <-> raw code, over the whole range. */
static void t_channel_mapping(void)
{
    int bad = 0, out_of_range = 0;
    uint8_t seen_raw[256] = {0};
    for (int n = 0; n < 128; n++) {
        uint8_t raw = FPGA_SPI_ChannelToRaw((uint8_t)n);
        if (FPGA_SPI_RawToChannel(raw) != (uint8_t)n) bad++;
        if (seen_raw[raw]++) bad++;                 /* must be injective */
        if ((raw & 0x3F) > 31) out_of_range++;      /* index within a module */
    }
    CHECK(bad == 0, "%d friendly<->raw round-trip or collision failures", bad);
    CHECK(out_of_range == 0, "%d raw codes name a slot > 31", out_of_range);
}

int main(void)
{
    printf("MCU SPI0 console — host verification against an A.1.1g FPGA model\n");
    printf("================================================================\n");
    t_reg_write16();
    t_reg_read16();
    t_16bit_width();
    t_roundtrip_all_words();
    t_sampling_slot();
    t_control_words();
    t_read_samples();
    t_no_dangling_sequences();
    t_channel_mapping();
    printf("%d checks, %d failures\n", checks, failures);
    printf(failures ? "FAILED\n" : "ALL PASSED\n");
    return failures ? 1 : 0;
}
