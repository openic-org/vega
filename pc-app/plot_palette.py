"""
Vega dark-theme color palette.

Usage:
    from plot_palette import PALETTE, apply_dark_axes

    fig, ax = plt.subplots()
    apply_dark_axes(fig, ax)
    ax.plot(x, y, color=PALETTE['cyan'])
"""

PALETTE = {
    # Backgrounds
    "bg":        "#0e1117",   # figure / outermost background
    "axes_bg":   "#161b22",   # individual axes background
    "grid":      "#2a2d35",   # spine and grid lines

    # Data series (high-contrast on dark)
    "cyan":      "#00c8ff",   # CH0 / primary series
    "orange":    "#ff6b35",   # CH1 / secondary series
    "green":     "#44dd88",   # good / after-fix highlight
    "red":       "#ff4444",   # bad / gaps / errors
    "yellow":    "#ffcc00",   # reference lines / warnings

    # Text
    "white":     "#e8eaf0",   # labels, tick marks, annotations
}


def fig_defaults(fig):
    """Apply dark background to a figure."""
    fig.patch.set_facecolor(PALETTE["bg"])


def apply_dark_axes(ax, xlabel="", ylabel="", title=""):
    """Style a single Axes with the dark theme."""
    ax.set_facecolor(PALETTE["axes_bg"])
    ax.spines[:].set_color(PALETTE["grid"])
    ax.tick_params(colors=PALETTE["white"])
    ax.xaxis.label.set_color(PALETTE["white"])
    ax.yaxis.label.set_color(PALETTE["white"])
    ax.title.set_color(PALETTE["white"])
    for lb in ax.get_xticklabels() + ax.get_yticklabels():
        lb.set_color(PALETTE["white"])
    if xlabel:
        ax.set_xlabel(xlabel, color=PALETTE["white"])
    if ylabel:
        ax.set_ylabel(ylabel, color=PALETTE["white"])
    if title:
        ax.set_title(title, color=PALETTE["white"])


def dark_legend(ax, **kwargs):
    """Attach a dark-styled legend to ax."""
    ax.legend(
        facecolor=PALETTE["bg"],
        edgecolor=PALETTE["grid"],
        labelcolor=PALETTE["white"],
        **kwargs,
    )
