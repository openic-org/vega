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
- `variant` is set by the build, not by hand:

  | `variant` | Build | `clk` |
  |---|---|---|
  | 1 | 28 kSPS, recording (tunnel unused) | 42.504 MHz |
  | 2 | 25 kSPS, operating (tunnel frames) | 37.95 MHz |
  | 3 | 25 kSPS, bench (K4.2 test pattern; no `STATUS`) | 37.95 MHz |
  | 0, F | never used | — |

- Builds of different variants made from the same commit share a
  `release`; they get one row each.
- Bitstreams from before release 1 carry no ID. The logs identify them
  by SHA-256.

**Releases**

| `release` | `variant` | `design_id` | `kuntur` commit | Bitstream SHA-256 | Date | Used for |
|---|---|---|---|---|---|---|
| — | | | | | | *none yet; release 1 is the first build with `` `KUNTUR_RELEASE ``* |
