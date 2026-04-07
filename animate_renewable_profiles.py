"""Animated MP4/GIF visualization of hourly solar and wind availability per region.

This script reads renewable-profile NetCDF files (one for onshore wind, one for solar)
and a GeoJSON file with region shapes, then produces two separate animations – one
per technology – that show how the capacity-factor changes hour-by-hour across all
modelled regions over a user-defined time window.

Configuration
-------------
Edit the constants in the "User configuration" block below before running the script.
No command-line arguments are required; all settings are controlled via those constants.

Required inputs
~~~~~~~~~~~~~~~
``WIND_PROFILE``
    Path to ``profile_adm_onwind.nc`` (or equivalent onshore-wind NetCDF).
    Expected dimensions: ``(year, time, bus, bin)`` or ``(time, bus)`` after
    squeezing singleton axes.

``SOLAR_PROFILE``
    Path to ``profile_adm_solar.nc`` (or equivalent solar NetCDF).
    Same dimension contract as above.

``REGIONS_GEOJSON``
    Path to a GeoJSON file with region polygons.  The file must contain a
    ``"name"`` column that matches the ``bus`` coordinate of the NetCDF files.

``START_DATE`` / ``END_DATE``
    ISO-8601 date strings (``"YYYY-MM-DD"`` or ``"YYYY-MM-DDTHH:MM"``).
    The animation covers every hourly timestep in the closed interval
    ``[START_DATE, END_DATE]``.

Outputs
~~~~~~~
``OUTPUT_WIND``
    Destination path for the wind animation (``*.mp4`` or ``*.gif``).

``OUTPUT_SOLAR``
    Destination path for the solar animation (``*.mp4`` or ``*.gif``).

``FPS``
    Frames per second for the output video.

Dependencies
~~~~~~~~~~~~
All core dependencies are declared in ``pixi.toml``:

* ``matplotlib >= 3.7`` – figure, animation, colormaps
* ``geopandas >= 0.14`` – region polygon I/O and plotting
* ``xarray >= 2023`` – NetCDF I/O
* ``numpy >= 1.24`` – numerical operations
* ``pandas >= 2.0`` – time index handling

Optional (for GIF fallback when ``ffmpeg`` is not available):

* ``pillow`` – GIF export via ``matplotlib``'s Pillow writer

Usage
-----
.. code-block:: bash

    pixi run python animate_renewable_profiles.py

or, if dependencies are installed manually:

.. code-block:: bash

    python animate_renewable_profiles.py
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.animation import FFMpegWriter, FuncAnimation, PillowWriter

# ---------------------------------------------------------------------------
# User configuration – edit these values before running
# ---------------------------------------------------------------------------

# Paths to the NetCDF profile files
WIND_PROFILE = Path("resources/profile_adm_onwind.nc")
SOLAR_PROFILE = Path("resources/profile_adm_solar.nc")

# Path to the region geometry file
REGIONS_GEOJSON = Path("resources/regions_onshore_base_s_adm.geojson")

# Animation time window (ISO-8601 strings)
START_DATE = "2013-05-01"
END_DATE = "2013-05-05"

# Output file paths  (.mp4 preferred; .gif used as fallback when ffmpeg is absent)
OUTPUT_WIND = Path("outputs/wind_availability.gif")
OUTPUT_SOLAR = Path("outputs/solar_availability.mp4")

# Frames per second for the output animation
FPS = 5

# ---------------------------------------------------------------------------
# Visual settings (change only if you want to adjust the look)
# ---------------------------------------------------------------------------

WIND_CMAP_NAME = "Blues"
SOLAR_CMAP_NAME = "YlOrRd"

FIGURE_SIZE = (10, 8)
EDGE_COLOR = "white"
EDGE_WIDTH = 0.4
MISSING_COLOR = "#cccccc"  # gray fill for regions with no matching profile value

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def load_profile(path: Path) -> xr.DataArray:
    """Load a renewable-capacity-factor NetCDF and return a 2-D ``(time, bus)`` DataArray.

    The function accepts files with the full ``(year, time, bus, bin)`` dimension
    layout produced by PyPSA-Eur / pypsa-at as well as simpler ``(time, bus)``
    layouts.  Singleton ``year`` and ``bin`` axes are squeezed away automatically.

    Parameters
    ----------
    path:
        Path to the NetCDF file.

    Returns
    -------
    xr.DataArray
        DataArray with dimensions ``(time, bus)`` and values in ``[0, 1]``.

    Raises
    ------
    FileNotFoundError
        When *path* does not exist.
    ValueError
        When required dimensions are missing after squeezing.
    """
    if not path.exists():
        raise FileNotFoundError(f"Profile file not found: {path}")

    log.info("Loading profile: %s", path)
    ds = xr.open_dataset(path)

    # The variable name may differ; pick the first data variable
    var_name = list(ds.data_vars)[0] if ds.data_vars else None
    if var_name is None:
        raise ValueError(f"No data variables found in {path}")

    da: xr.DataArray = ds[var_name]
    log.info("  Variable '%s', dims=%s, shape=%s", var_name, da.dims, da.shape)

    # Squeeze away singleton year and bin dimensions when present
    squeeze_dims = [d for d in ("year", "bin") if d in da.dims and da.sizes[d] == 1]
    if squeeze_dims:
        da = da.squeeze(squeeze_dims)

    # Select the first year / bin if still multi-valued
    if "year" in da.dims:
        log.warning("  Multiple years found – selecting first year (index 0).")
        da = da.isel(year=0)
    if "bin" in da.dims:
        log.warning("  Multiple bins found – selecting first bin (index 0).")
        da = da.isel(bin=0)

    # Validate required dimensions
    for required in ("time", "bus"):
        if required not in da.dims:
            raise ValueError(
                f"Required dimension '{required}' not found in {path}. "
                f"Available dims after squeezing: {da.dims}"
            )

    log.info("  Final shape after squeezing: %s", dict(zip(da.dims, da.shape)))
    return da


def load_regions(geojson_path: Path) -> gpd.GeoDataFrame:
    """Load region polygons from a GeoJSON file.

    The function sets the ``"name"`` column as the DataFrame index and
    reprojects to WGS-84 (EPSG:4326) if necessary.

    Parameters
    ----------
    geojson_path:
        Path to the GeoJSON file containing region polygons.

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame indexed by region name.

    Raises
    ------
    FileNotFoundError
        When *geojson_path* does not exist.
    KeyError
        When the ``"name"`` column is missing.
    """
    if not geojson_path.exists():
        raise FileNotFoundError(f"Regions file not found: {geojson_path}")

    log.info("Loading regions: %s", geojson_path)
    gdf = gpd.read_file(geojson_path)

    if "name" not in gdf.columns:
        raise KeyError(
            f"Column 'name' not found in {geojson_path}. "
            f"Available columns: {list(gdf.columns)}"
        )

    gdf = gdf.set_index("name")

    if gdf.crs is None:
        log.warning("  CRS not set – assuming EPSG:4326.")
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        log.info("  Reprojecting from %s to EPSG:4326.", gdf.crs)
        gdf = gdf.to_crs("EPSG:4326")

    log.info("  Loaded %d regions.", len(gdf))
    return gdf


# ---------------------------------------------------------------------------
# Time-selection helpers
# ---------------------------------------------------------------------------


def parse_date(date_str: str) -> pd.Timestamp:
    """Parse an ISO-8601 date/datetime string to a :class:`pandas.Timestamp`."""
    return pd.Timestamp(date_str)


def select_time_window(
    da: xr.DataArray,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> xr.DataArray:
    """Subset *da* to the closed time interval ``[start, end]``.

    Parameters
    ----------
    da:
        DataArray with a ``time`` dimension.
    start:
        Start timestamp (inclusive).
    end:
        End timestamp (inclusive).

    Returns
    -------
    xr.DataArray
        Subset DataArray.

    Raises
    ------
    ValueError
        When no timesteps fall within the specified window.
    """
    times = pd.DatetimeIndex(da.time.values)
    mask = (times >= start) & (times <= end)

    if not mask.any():
        first = times[0]
        last = times[-1]
        raise ValueError(
            f"No timesteps found between {start} and {end}. "
            f"Profile time range: {first} – {last}."
        )

    subset = da.sel(time=da.time.values[mask])
    log.info(
        "  Selected %d timesteps from %s to %s.",
        int(mask.sum()),
        times[mask][0],
        times[mask][-1],
    )
    return subset


# ---------------------------------------------------------------------------
# Frame-building helpers
# ---------------------------------------------------------------------------


def build_frame_gdf(
    gdf: gpd.GeoDataFrame,
    bus_values: pd.Series,
) -> tuple[gpd.GeoDataFrame, set[str]]:
    """Attach capacity-factor values from *bus_values* to a copy of *gdf*.

    Regions that have no matching value in *bus_values* are filled with
    ``NaN`` and will be drawn in the missing-region colour.

    Parameters
    ----------
    gdf:
        Region GeoDataFrame indexed by region name.
    bus_values:
        Series indexed by bus/region name, values in ``[0, 1]``.

    Returns
    -------
    tuple[gpd.GeoDataFrame, set[str]]
        * A copy of *gdf* with a ``"profile"`` column added.
        * A set of region names that had no matching profile value.
    """
    frame = gdf.copy()
    frame["profile"] = bus_values.reindex(frame.index)

    unmatched = set(frame.index[frame["profile"].isna()])
    return frame, unmatched


# ---------------------------------------------------------------------------
# Animation builder
# ---------------------------------------------------------------------------


def _make_colormap(cmap_name: str) -> mcolors.Colormap:
    """Return the named colormap.

    Colormaps such as ``"Blues"`` and ``"YlOrRd"`` naturally span
    0 (near-white) → 1 (darkest shade), which is exactly the visual
    encoding required.  The :class:`~matplotlib.colors.Normalize` used
    at call sites constrains values to ``[0, 1]``, so no additional
    remapping is needed here.
    """
    return cm.get_cmap(cmap_name, 256)


def animate_profile(
    da: xr.DataArray,
    gdf: gpd.GeoDataFrame,
    output_path: Path,
    cmap_name: str,
    label: str,
    fps: int,
) -> None:
    """Generate and save an animation for a single technology profile.

    Parameters
    ----------
    da:
        DataArray ``(time, bus)`` with capacity-factor values in ``[0, 1]``.
    gdf:
        Region GeoDataFrame indexed by bus/region name.
    output_path:
        Destination file path (``*.mp4`` or ``*.gif``).
    cmap_name:
        Matplotlib colormap name (e.g. ``"Blues"`` or ``"YlOrRd"``).
    label:
        Technology label shown in the colorbar title (e.g. ``"Wind"``).
    fps:
        Frames per second.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmap = _make_colormap(cmap_name)
    norm = mcolors.Normalize(vmin=0.0, vmax=1.0)

    times = pd.DatetimeIndex(da.time.values)
    n_frames = len(times)
    log.info("Building %s animation: %d frames → %s", label, n_frames, output_path)

    # -- Figure setup --------------------------------------------------------
    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.axis("off")

    bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
    pad_x = (bounds[2] - bounds[0]) * 0.02
    pad_y = (bounds[3] - bounds[1]) * 0.02
    ax.set_xlim(bounds[0] - pad_x, bounds[2] + pad_x)
    ax.set_ylim(bounds[1] - pad_y, bounds[3] + pad_y)

    # Colorbar
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label(f"{label} availability factor", fontsize=10)

    # Title placeholder
    title_obj = ax.set_title("", fontsize=12, pad=8)

    # Track whether we warned about unmatched regions already
    warned_unmatched: set[str] = set()

    # -- Frame function ------------------------------------------------------
    def draw_frame(i: int) -> list:
        ax.cla()
        ax.axis("off")
        ax.set_xlim(bounds[0] - pad_x, bounds[2] + pad_x)
        ax.set_ylim(bounds[1] - pad_y, bounds[3] + pad_y)

        t = times[i]
        bus_values = pd.Series(
            da.isel(time=i).values,
            index=da.bus.values,
        )

        frame_gdf, unmatched = build_frame_gdf(gdf, bus_values)

        # Warn once about unmatched regions
        new_unmatched = unmatched - warned_unmatched
        if new_unmatched:
            log.warning(
                "  Frame %d (%s): %d region(s) have no profile value → drawn gray. "
                "First few: %s",
                i,
                t,
                len(new_unmatched),
                sorted(new_unmatched)[:5],
            )
            warned_unmatched.update(new_unmatched)

        # Draw regions with missing values in gray
        missing_mask = frame_gdf["profile"].isna()
        if missing_mask.any():
            frame_gdf[missing_mask].plot(
                ax=ax,
                color=MISSING_COLOR,
                edgecolor=EDGE_COLOR,
                linewidth=EDGE_WIDTH,
            )

        # Draw regions with valid values using the colormap
        if (~missing_mask).any():
            frame_gdf[~missing_mask].plot(
                ax=ax,
                column="profile",
                cmap=cmap,
                norm=norm,
                edgecolor=EDGE_COLOR,
                linewidth=EDGE_WIDTH,
                legend=False,
            )

        ax.set_title(
            f"{label} availability  –  {t.strftime('%Y-%m-%d %H:%M')}",
            fontsize=12,
            pad=8,
        )

        if (i + 1) % max(1, n_frames // 10) == 0 or i == n_frames - 1:
            log.info("  Generated frame %d / %d", i + 1, n_frames)

        return []

    # -- Animation assembly --------------------------------------------------
    anim = FuncAnimation(
        fig,
        draw_frame,
        frames=n_frames,
        interval=1000 // fps,
        blit=False,
    )

    saved = _save_animation(anim, output_path, fps)
    plt.close(fig)
    log.info("Saved %s animation to: %s", label, saved)


def _save_animation(anim: FuncAnimation, output_path: Path, fps: int) -> Path:
    """Save *anim* to *output_path*, falling back from MP4 to GIF if needed.

    The function first attempts to use :class:`~matplotlib.animation.FFMpegWriter`
    (requires ``ffmpeg`` on ``PATH``).  When that is unavailable it falls back to
    :class:`~matplotlib.animation.PillowWriter` and adjusts the file extension to
    ``.gif`` automatically.

    Parameters
    ----------
    anim:
        :class:`~matplotlib.animation.FuncAnimation` instance.
    output_path:
        Desired output path.  Extension may be changed to ``.gif`` on fallback.
    fps:
        Frames per second.

    Returns
    -------
    Path
        Actual path the file was saved to (may differ in extension from *output_path*).
    """
    # Try MP4 first
    if output_path.suffix.lower() == ".mp4":
        # isAvailable() is the actual matplotlib API name (camelCase by design)
        if FFMpegWriter.isAvailable():  # type: ignore[attr-defined]
            writer = FFMpegWriter(fps=fps, metadata={"title": output_path.stem})
            anim.save(str(output_path), writer=writer)
            return output_path
        else:
            log.warning(
                "ffmpeg not found – falling back to GIF output. "
                "Install ffmpeg to produce MP4 files."
            )
            output_path = output_path.with_suffix(".gif")

    # GIF fallback
    writer = PillowWriter(fps=fps)
    anim.save(str(output_path), writer=writer)
    return output_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Validate inputs, load data, and produce both wind and solar animations."""
    log.info("=== animate_renewable_profiles.py ===")
    log.info("Wind profile  : %s", WIND_PROFILE)
    log.info("Solar profile : %s", SOLAR_PROFILE)
    log.info("Regions       : %s", REGIONS_GEOJSON)
    log.info("Time window   : %s → %s", START_DATE, END_DATE)
    log.info("Output wind   : %s", OUTPUT_WIND)
    log.info("Output solar  : %s", OUTPUT_SOLAR)
    log.info("FPS           : %d", FPS)

    start = parse_date(START_DATE)
    end = parse_date(END_DATE)
    if end < start:
        raise ValueError(f"END_DATE ({end}) must be >= START_DATE ({start}).")

    # Load regions once (shared by both technologies)
    gdf = load_regions(REGIONS_GEOJSON)

    # Process wind
    log.info("--- Wind ---")
    da_wind = load_profile(WIND_PROFILE)
    da_wind = select_time_window(da_wind, start, end)
    animate_profile(
        da=da_wind,
        gdf=gdf,
        output_path=OUTPUT_WIND,
        cmap_name=WIND_CMAP_NAME,
        label="Wind",
        fps=FPS,
    )

    # Process solar
    log.info("--- Solar ---")
    da_solar = load_profile(SOLAR_PROFILE)
    da_solar = select_time_window(da_solar, start, end)
    animate_profile(
        da=da_solar,
        gdf=gdf,
        output_path=OUTPUT_SOLAR,
        cmap_name=SOLAR_CMAP_NAME,
        label="Solar",
        fps=FPS,
    )

    log.info("=== Done ===")


if __name__ == "__main__":
    main()
