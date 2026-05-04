"""
Vega time-series analysis plot template.

Produces a 3-row, 2-column dark-theme figure:
  Row 1 (full width) : full waveform
  Row 2 left         : zoomed window
  Row 2 right        : Δt histogram
  Row 3 left         : gap / event timeline
  Row 3 right        : statistics text panel

Adapt the ── CONFIGURE ── section at the top, then run:
    python plot_template.py
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")          # change to "TkAgg" / "Qt5Agg" for interactive
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from plot_palette import PALETTE, fig_defaults, apply_dark_axes, dark_legend

# ── CONFIGURE ────────────────────────────────────────────────────────────────

CSV_FILE     = "vega_20260504_151311.csv"   # path to your CSV
OUTPUT_FILE  = "/tmp/vega_plot.png"         # where to save the figure
DPI          = 150

# Column names / indices in the CSV (0-based after header row)
COL_TIME     = 0    # timestamp in microseconds
COL_CH0      = 1    # first channel
COL_CH1      = 2    # second channel (set to None to skip)

SAMPLE_RATE  = 30_000          # Hz — used to compute expected Δt
GAP_THRESH   = 2.0             # multiples of expected Δt to call a gap

# Zoom window (seconds from start of recording)
ZOOM_START_S = 3.0
ZOOM_WIDTH_S = 0.20

TITLE = "Vega ADC recording — analysis"

# ── LOAD & PREPARE ───────────────────────────────────────────────────────────

raw        = np.loadtxt(CSV_FILE, delimiter=",", skiprows=1)
ts_us      = raw[:, COL_TIME]
ch0        = raw[:, COL_CH0]
ch1        = raw[:, COL_CH1] if COL_CH1 is not None else None

n          = len(ts_us)
t_s        = (ts_us - ts_us[0]) / 1e6        # relative time in seconds
duration_s = t_s[-1]
eff_sps    = n / duration_s

dt         = np.diff(ts_us)
step_us    = 1_000_000 / SAMPLE_RATE
gap_mask   = dt > step_us * GAP_THRESH
neg_mask   = dt < 0
gap_t_s    = t_s[:-1][gap_mask]
gap_us     = dt[gap_mask]

# ── FIGURE LAYOUT ────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(16, 14))
fig_defaults(fig)
gs = gridspec.GridSpec(
    3, 2, figure=fig,
    hspace=0.40, wspace=0.30,
    left=0.07, right=0.97, top=0.93, bottom=0.06,
)

# ── PANEL 1 : Full waveform ───────────────────────────────────────────────────

ax1 = fig.add_subplot(gs[0, :])
s   = slice(None, None, max(1, n // 5000))   # ~5000 points for speed
ax1.plot(t_s[s], ch0[s], color=PALETTE["cyan"],   lw=0.4, alpha=0.85, label="CH0")
if ch1 is not None:
    ax1.plot(t_s[s], ch1[s], color=PALETTE["orange"], lw=0.4, alpha=0.85, label="CH1")
for g_t, g_u in zip(gap_t_s, gap_us):
    ax1.axvspan(g_t, g_t + g_u / 1e6, color=PALETTE["red"], alpha=0.12)
ax1.set_xlim(0, duration_s)
apply_dark_axes(ax1, xlabel="Time (s)", ylabel="Value",
                title=f"Full recording  ({n:,} samples, {eff_sps:,.0f} SPS)")
dark_legend(ax1, loc="upper right")

# ── PANEL 2 : Zoom ────────────────────────────────────────────────────────────

ax2  = fig.add_subplot(gs[1, 0])
z0   = ZOOM_START_S
z1   = z0 + ZOOM_WIDTH_S
zm   = (t_s >= z0) & (t_s <= z1)
ax2.plot(t_s[zm], ch0[zm], color=PALETTE["cyan"],   lw=0.9, label="CH0")
if ch1 is not None:
    ax2.plot(t_s[zm], ch1[zm], color=PALETTE["orange"], lw=0.9, label="CH1")
zm_gap = (gap_t_s >= z0) & (gap_t_s <= z1)
for g_t, g_u in zip(gap_t_s[zm_gap], gap_us[zm_gap]):
    ax2.axvspan(g_t, min(g_t + g_u / 1e6, z1), color=PALETTE["red"], alpha=0.40)
ax2.set_xlim(z0, z1)
apply_dark_axes(ax2, xlabel="Time (s)", ylabel="Value",
                title=f"{ZOOM_WIDTH_S*1000:.0f} ms zoom (red = gap)")
dark_legend(ax2, loc="upper right", fontsize=8)

# ── PANEL 3 : Δt histogram ────────────────────────────────────────────────────

ax3  = fig.add_subplot(gs[1, 1])
bins = np.linspace(min(-step_us, dt.min()) * 1.1, min(dt.max(), step_us * 20), 200)
c, e = np.histogram(np.clip(dt, bins[0], bins[-1]), bins=bins)
ax3.bar((e[:-1]+e[1:])/2, c, width=(e[1]-e[0]),
        color=PALETTE["cyan"], alpha=0.75, edgecolor="none")
ax3.axvline(step_us, color=PALETTE["yellow"], lw=1.5, ls="--",
            label=f"Expected {step_us:.1f} µs")
ax3.axvline(0, color=PALETTE["white"], lw=1.0, ls=":", alpha=0.5, label="Zero")
ax3.set_yscale("log"); ax3.set_ylim(bottom=0.9)
apply_dark_axes(ax3, xlabel="Δt (µs)", ylabel="Count (log)",
                title="Sample-to-sample Δt distribution")
dark_legend(ax3, fontsize=8)

# ── PANEL 4 : Gap timeline ────────────────────────────────────────────────────

ax4 = fig.add_subplot(gs[2, 0])
if len(gap_t_s):
    ax4.scatter(gap_t_s, gap_us / 1000, s=5, color=PALETTE["red"], alpha=0.6)
ax4.axhline(step_us * GAP_THRESH / 1000, color=PALETTE["yellow"],
            lw=1.0, ls="--", label=f"Threshold ({GAP_THRESH}×Δt)")
ax4.set_xlim(0, duration_s)
apply_dark_axes(ax4, xlabel="Time (s)", ylabel="Gap size (ms)",
                title=f"{gap_mask.sum():,} gaps  (Δt > {GAP_THRESH}×expected)")
dark_legend(ax4, fontsize=8)

# ── PANEL 5 : Statistics ──────────────────────────────────────────────────────

ax5 = fig.add_subplot(gs[2, 1])
ax5.set_facecolor(PALETTE["axes_bg"]); ax5.axis("off")

rows = [
    ("SIGNAL",          None),
    ("Duration",        f"{duration_s:.3f} s"),
    ("Samples",         f"{n:,}"),
    ("Effective SPS",   f"{eff_sps:,.0f}"),
    ("",                None),
    ("TIMESTAMPS",      None),
    ("Median Δt",       f"{np.median(dt):.1f} µs"),
    ("Std dev",         f"{dt.std():.1f} µs"),
    ("Backwards Δt",    f"{neg_mask.sum():,}"),
    ("Min / max Δt",    f"{dt.min():.0f} / {dt.max():.0f} µs"),
    ("",                None),
    ("GAPS",            None),
    ("Count",           f"{gap_mask.sum():,}"),
    ("Total gap time",  f"{gap_us.sum()/1e6:.3f} s  ({100*gap_us.sum()/(ts_us[-1]-ts_us[0]):.1f}%)"),
    ("Largest gap",     f"{gap_us.max()/1000:.1f} ms" if len(gap_us) else "—"),
]
y = 0.97
for key, val in rows:
    if val is None:
        ax5.text(0.02, y, key, color=PALETTE["yellow"], fontsize=9, fontweight="bold",
                 transform=ax5.transAxes, va="top")
    else:
        ax5.text(0.02, y, key,  color=PALETTE["white"], fontsize=8.5,
                 transform=ax5.transAxes, va="top")
        ax5.text(0.98, y, val, color=PALETTE["cyan"],  fontsize=8.5,
                 transform=ax5.transAxes, va="top", ha="right")
    y -= 0.060
ax5.set_title("Statistics", color=PALETTE["white"], fontsize=10)

# ── SAVE ──────────────────────────────────────────────────────────────────────

fig.suptitle(TITLE, color=PALETTE["white"], fontsize=13, y=0.97)
plt.savefig(OUTPUT_FILE, dpi=DPI, bbox_inches="tight",
            facecolor=PALETTE["bg"])
print(f"Saved: {OUTPUT_FILE}")
