"""Austria-focused transparent network visualization.

Produces a PNG figure with:
- Austria polygon filled with a bright colour
- Transmission lines and links drawn in contrasting colours, widths
  proportional to s_nom / p_nom
- No buses drawn
- Fully transparent figure and axes background

Derived from plot_base_network.py in the PyPSA-Eur repository
(https://github.com/PyPSA/pypsa-eur/blob/master/scripts/plot_base_network.py).

Usage
-----
1. Set NETWORK_FILE, REGIONS_ONSHORE_FILE and OUTPUT_PNG below.
2. Run:  python plot_austria_network.py
"""

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import geopandas as gpd
import pypsa

# ---------------------------------------------------------------------------
# Configuration – set these paths before running
# ---------------------------------------------------------------------------

NETWORK_FILE = "path/to/network.nc"
REGIONS_ONSHORE_FILE = "path/to/regions_onshore.geojson"
OUTPUT_PNG = "austria_network.png"

# Index key used for Austria in the regions file.
# Common values: "AT" (PyPSA-Eur country level), "AT0" (NUTS-0).
# The loader falls back to a prefix match ("AT…") when the exact key is absent.
AUSTRIA_KEY = "AT"

# Visual settings
AUSTRIA_FACECOLOR = "#4A90D9"  # bright blue fill for Austria
AUSTRIA_EDGECOLOR = "white"
AUSTRIA_ALPHA = 0.7
LINE_COLOR = "#FFB347"  # orange for AC lines
LINK_COLOR = "#FF6B6B"  # coral/red for DC links
LINE_WIDTH_FACTOR = 2e3  # divisor for s_nom → line width scaling
LINK_WIDTH_FACTOR = 2e3  # divisor for p_nom → link width scaling

# Padding added to Austria's bounding box when setting the axis extent (degrees)
EXTENT_PADDING = 0.5

# Output resolution
OUTPUT_DPI = 150

# ---------------------------------------------------------------------------
# Compatibility patch
# ---------------------------------------------------------------------------


def _patch_pypsa_apply_cmap() -> None:
    """Patch PyPSA's apply_cmap to handle pandas 2.x StringDtype.

    In pandas ≥ 2.0 creating a Series from a plain string scalar yields a
    column with ``StringDtype``.  PyPSA's ``apply_cmap`` passes that directly
    to ``numpy.issubdtype``, which cannot handle pandas extension types and
    raises ``TypeError`` (confirmed in PyPSA 1.1.2; fixed status in later
    versions unknown).  This patch wraps the dtype check in a try/except so
    that string-colour columns fall through unchanged.  The patch is a no-op
    on versions where the bug is already fixed.

    The patch is applied to the local name in ``pypsa.plot.maps.static``
    (where ``apply_cmap`` is imported by name) rather than to the source
    module, so it does not affect any other code.
    """
    import pypsa.plot.maps.static as _static

    _orig = _static.apply_cmap

    def _safe_apply_cmap(
        colors,
        cmap,
        cmap_norm=None,
    ):
        try:
            is_numeric = np.issubdtype(colors.dtype, np.number)
        except TypeError:
            is_numeric = False
        if is_numeric:
            if not isinstance(cmap, mcolors.Colormap):
                cmap = plt.get_cmap(cmap)
            if not cmap_norm:
                cmap_norm = plt.Normalize(vmin=colors.min(), vmax=colors.max())
            colors = colors.apply(lambda v: cmap(cmap_norm(v)))
        return colors

    _static.apply_cmap = _safe_apply_cmap


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def load_regions(regions_file: str, austria_key: str = AUSTRIA_KEY) -> gpd.GeoDataFrame:
    """Load onshore regions and return the Austria polygon(s).

    The function first tries an exact index match on *austria_key* (e.g.
    ``"AT"``).  When no exact match is found it falls back to all entries
    whose index starts with *austria_key* (e.g. ``"AT0"``, ``"AT11"`` …).

    Parameters
    ----------
    regions_file:
        Path to a GeoJSON / shapefile with onshore regions.  The file must
        have a column ``"name"`` that is used as the index.
    austria_key:
        Index label (or prefix) identifying Austria.

    Raises
    ------
    ValueError
        When no matching region can be found.
    """
    regions = gpd.read_file(regions_file).set_index("name")

    austria = regions[regions.index == austria_key]
    if austria.empty:
        austria = regions[regions.index.str.startswith(austria_key)]

    if austria.empty:
        available = ", ".join(regions.index[:20].tolist())
        raise ValueError(
            f"No region matching '{austria_key}' found in '{regions_file}'. "
            f"Available keys (first 20): {available}"
        )
    return austria


def make_figure() -> tuple:
    """Create a figure and axes with fully transparent backgrounds.

    Returns
    -------
    tuple[matplotlib.figure.Figure, matplotlib.axes.Axes]
    """
    fig, ax = plt.subplots(figsize=(8, 8))
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return fig, ax


def plot_austria(ax, austria: gpd.GeoDataFrame) -> None:
    """Draw Austria polygon(s) on *ax*.

    Parameters
    ----------
    ax:
        Matplotlib axes to draw on.
    austria:
        GeoDataFrame containing Austria geometry (any CRS).
    """
    austria.to_crs("EPSG:4326").plot(
        ax=ax,
        facecolor=AUSTRIA_FACECOLOR,
        edgecolor=AUSTRIA_EDGECOLOR,
        linewidth=0.5,
        alpha=AUSTRIA_ALPHA,
    )


def plot_network(ax, n: pypsa.Network) -> None:
    """Draw lines and links (no buses) on *ax*.

    Line widths are scaled proportionally to ``s_nom`` (lines) and
    ``p_nom`` (links).

    Parameters
    ----------
    ax:
        Matplotlib axes to draw on.
    n:
        Loaded PyPSA network.
    """
    line_width = n.lines.s_nom / LINE_WIDTH_FACTOR if not n.lines.empty else 0
    link_width = n.links.p_nom / LINK_WIDTH_FACTOR if not n.links.empty else 0

    n.plot(
        ax=ax,
        geomap=False,
        bus_size=0,
        line_color=LINE_COLOR,
        link_color=LINK_COLOR,
        line_width=line_width,
        link_width=link_width,
    )


def set_austria_extent(ax, austria: gpd.GeoDataFrame) -> None:
    """Zoom *ax* to Austria's bounding box plus padding.

    Parameters
    ----------
    ax:
        Matplotlib axes to adjust.
    austria:
        GeoDataFrame containing Austria geometry.
    """
    bounds = austria.to_crs("EPSG:4326").total_bounds  # [minx, miny, maxx, maxy]
    ax.set_xlim(bounds[0] - EXTENT_PADDING, bounds[2] + EXTENT_PADDING)
    ax.set_ylim(bounds[1] - EXTENT_PADDING, bounds[3] + EXTENT_PADDING)


def main() -> None:
    """Load data, build the figure, and save the output PNG."""
    _patch_pypsa_apply_cmap()

    n = pypsa.Network(NETWORK_FILE)
    austria = load_regions(REGIONS_ONSHORE_FILE)

    fig, ax = make_figure()
    plot_austria(ax, austria)
    plot_network(ax, n)
    set_austria_extent(ax, austria)

    ax.axis("off")

    plt.savefig(
        OUTPUT_PNG,
        bbox_inches="tight",
        transparent=True,
        dpi=OUTPUT_DPI,
    )
    plt.close()
    print(f"Saved to {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
