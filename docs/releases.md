# Kuntur FPGA releases

Every Kuntur bitstream flashed for a session whose data is kept gets a
`release` number, and is recorded here. The number goes into
`design_id = {variant[3:0], release[11:0]}`, which Kuntur sends in every
tunnel `STATUS` frame (`docs/interfaces/lvds-tunnel.md` §4.4a) and, once
R-K6 is built, in its regbank status word
(`docs/interfaces/system-startup.md`).

**Rules**

- `release` is set by hand: `` `KUNTUR_RELEASE `` in the Kuntur RTL.
  Bump it before building a bitstream that will be flashed for a logged
  bench run, the dress rehearsal (R5) or the animal test.
- Iteration builds use `release` 0, "development build". They are never
  recorded here and never used for kept data.
- `variant` is set by the build, not by hand: each Radiant
  implementation defines `` `KUNTUR_VARIANT `` in its Verilog directives
  (`VERILOG_DIRECTIVES`, sized, e.g. `KUNTUR_VARIANT=4'd2`), which
  overrides `kuntur_build.vh` (PLAN.md R1, task #6, agreed 2026-11-04):

  | `variant` | Implementation | Build | `clk` (PLL IP) | Tunnel carries | `design_id` at release *r* |
  |---|---|---|---|---|---|
  | 1 | `impl_28k` | 28 kSPS, recording (tunnel unused) | 42.504 MHz (`pll_28k`) | `00` only | `0x1rrr` |
  | 2 | `impl_25k` | 25 kSPS, operating | 37.95 MHz (`pll_25k`) | frames (`SAMPLE`, `CONFIG`, `STATUS`) | `0x2rrr` |
  | 3 | `impl_25k_bench` | 25 kSPS, bench | 37.95 MHz (`pll_25k`) | K4.2 test pattern; no frames, so no `STATUS` | `0x3rrr` |
  | 0, 4–F | — | never used: `frame_selector` stops the build | — | — | — |

  `impl_25k` and `impl_25k_bench` share one `.sdc`; all three share the
  RTL and the `.pdc`. Until #6 lands, the project still has the single
  45.54 MHz `impl_1`, and the variant comes from `kuntur_build.vh`.

- Builds of different variants made from the same commit share a
  `release`; they get one row each.
- Bitstreams from before release 1 carry no ID. The logs identify them
  by SHA-256.

**Releases**

| `release` | `variant` | `design_id` | `kuntur` commit | Bitstream SHA-256 | Date | Used for |
|---|---|---|---|---|---|---|
| — | | | | | | *none yet; release 1 is the first build with `` `KUNTUR_RELEASE ``* |
