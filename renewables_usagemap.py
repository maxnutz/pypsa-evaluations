from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import plotly.graph_objects as go
import pypsa

# Set the path to the file to evaluate and to the file with onshore-regions
# offshore-regions are not yet included
NETWORK_PATH = Path(
    "/home/maxnutz/Documents/2026_EnInnov/run_outputs/pypsa-at-35/networks/base_s_adm__none_2050.nc"
)
FALLBACK_REGIONS_PATH = Path(
    "/home/maxnutz/Documents/2026_EnInnov/run_outputs/pypsa-at-35/regions_onshore_base_s_adm.geojson"
)
OUTPUT_HTML = Path(__file__).with_name("renewables_links_map.html")

# Set to True to evaluate/colour only Austrian regions (name starts with "AT").
# AC/DC links remain global in both modes.
EVALUATE_AUSTRIA_ONLY = False

# Set to True to draw a pie chart on each region, representing the local
# share of solar vs wind in that region's total renewables.
SHOW_REGION_PIE_CHARTS = True

# Pie radius in map degrees. Increase if pies should appear larger.
PIE_RADIUS_DEG = 0.1

# Select which regional metric should be visualized in map color and pie charts.
# "capacity": installed wind+solar capacity in GW.
# "production": produced electricity over the modeled period in TWh.
DISPLAY_METRIC = "production"

RENEWABLE_CARRIERS = {
	"onwind",
	"offwind-ac",
	"offwind-dc",
	"solar rooftop",
	"solar",
	"solar-hsat",
}

SOLAR_CARRIERS = {"solar rooftop", "solar", "solar-hsat"}
WIND_CARRIERS = {"onwind", "offwind-ac", "offwind-dc"}
WIND_PRODUCTION_CARRIERS = {"onwind"}


def normalize_region_name(bus_name: str) -> str:
	"""Map sector-specific bus names back to a geographic region key."""
	return bus_name.removesuffix(" low voltage")


def scale_width(values: pd.Series, min_w: float = 1.5, max_w: float = 12.0) -> pd.Series:
	"""Linearly scale capacities to plot widths in pixels."""
	if values.empty:
		return values
	v_min = float(values.min())
	v_max = float(values.max())
	if math.isclose(v_min, v_max):
		return pd.Series(min_w, index=values.index)
	return min_w + (values - v_min) * (max_w - min_w) / (v_max - v_min)


def load_region_geometries(network: pypsa.Network) -> gpd.GeoDataFrame:
	"""
	Load region polygons.

	The network contains a `shapes` table, but in this case it is empty,
	so we explicitly fall back to the matching resources geojson.
	"""
	if hasattr(network, "shapes") and getattr(network, "shapes") is not None:
		shapes = network.shapes
		if not shapes.empty and "geometry" in shapes.columns:
			gdf = gpd.GeoDataFrame(shapes.copy(), geometry="geometry", crs="EPSG:4326")
			if "name" not in gdf.columns:
				gdf = gdf.reset_index().rename(columns={"index": "name"})
			return gdf[["name", "geometry"]]

	print(
		"[INFO] No region polygons embedded in .nc network (n.shapes is empty). "
		f"Using fallback geojson: {FALLBACK_REGIONS_PATH}"
	)
	gdf = gpd.read_file(FALLBACK_REGIONS_PATH)
	if "name" not in gdf.columns:
		raise ValueError(f"GeoJSON file does not contain a 'name' column: {FALLBACK_REGIONS_PATH}")
	return gdf[["name", "geometry"]]


def calculate_renewable_capacities_gw(
	network: pypsa.Network,
	region_names: set[str],
	evaluate_austria_only: bool,
) -> pd.Series:
	"""Compute optimal wind+solar capacity per region in GW."""
	generators = network.generators.copy()
	generators = generators[generators["carrier"].isin(RENEWABLE_CARRIERS)]
	generators["region"] = generators["bus"].astype(str).map(normalize_region_name)
	generators = generators[generators["region"].isin(region_names)]
	if evaluate_austria_only:
		generators = generators[generators["region"].str.startswith("AT")]

	region_caps_gw = generators.groupby("region")["p_nom_opt"].sum() / 1000.0
	return region_caps_gw


def calculate_renewable_split_by_region_gw(
	network: pypsa.Network,
	region_names: set[str],
	evaluate_austria_only: bool,
) -> pd.DataFrame:
    """Compute solar/wind capacities and shares per region in GW."""
    generators = network.generators.copy()
    generators = generators[generators["carrier"].isin(RENEWABLE_CARRIERS)]
    generators["region"] = generators["bus"].astype(str).map(normalize_region_name)
    generators = generators[generators["region"].isin(region_names)]
    if evaluate_austria_only:
        generators = generators[generators["region"].str.startswith("AT")]

    generators["kind"] = generators["carrier"].map(
        lambda carrier: "solar" if carrier in SOLAR_CARRIERS else "wind"
    )

    split = (
        generators.groupby(["region", "kind"])["p_nom_opt"]
        .sum()
        .unstack(fill_value=0.0)
        .rename(columns={"solar": "solar_mw", "wind": "wind_mw"})
    )

    for col in ["solar_mw", "wind_mw"]:
        if col not in split.columns:
            split[col] = 0.0

    split["solar_value"] = split["solar_mw"] / 1000.0
    split["wind_value"] = split["wind_mw"] / 1000.0
    split["total_value"] = split["solar_value"] + split["wind_value"]

    nonzero = split["total_value"] > 0
    split["solar_share_pct"] = 0.0
    split["wind_share_pct"] = 0.0
    split.loc[nonzero, "solar_share_pct"] = (
        100.0 * split.loc[nonzero, "solar_value"] / split.loc[nonzero, "total_value"]
    )
    split.loc[nonzero, "wind_share_pct"] = (
        100.0 * split.loc[nonzero, "wind_value"] / split.loc[nonzero, "total_value"]
    )

    return split[
        [
            "solar_value",
            "wind_value",
            "total_value",
            "solar_share_pct",
            "wind_share_pct",
        ]
    ]


def calculate_renewable_production_split_by_region_twh(
    network: pypsa.Network,
    region_names: set[str],
    evaluate_austria_only: bool,
) -> pd.DataFrame:
    """Compute modeled-period solar/wind production and shares per region in TWh."""
    generators = network.generators.copy()
    production_carriers = SOLAR_CARRIERS | WIND_PRODUCTION_CARRIERS
    generators = generators[generators["carrier"].isin(production_carriers)]
    generators["region"] = generators["bus"].astype(str).map(normalize_region_name)
    generators = generators[generators["region"].isin(region_names)]
    if evaluate_austria_only:
        generators = generators[generators["region"].str.startswith("AT")]

    if generators.empty:
        return pd.DataFrame(
            columns=[
                "solar_value",
                "wind_value",
                "total_value",
                "solar_share_pct",
                "wind_share_pct",
            ]
        )

    dispatch = network.generators_t.p.loc[
        :, network.generators_t.p.columns.intersection(generators.index)
    ]
    generators = generators.loc[dispatch.columns].copy()
    if dispatch.empty:
        return pd.DataFrame(
            columns=[
                "solar_value",
                "wind_value",
                "total_value",
                "solar_share_pct",
                "wind_share_pct",
            ]
        )

    weights = network.snapshot_weightings.generators.reindex(dispatch.index).fillna(1.0)
    # Weighted sum over modeled snapshots: MW * h -> MWh.
    energy_mwh = dispatch.mul(weights, axis=0).sum(axis=0)
    generators["energy_mwh"] = energy_mwh.reindex(generators.index).fillna(0.0)
    generators["kind"] = generators["carrier"].map(
        lambda carrier: "solar" if carrier in SOLAR_CARRIERS else "wind"
    )

    split = (
        generators.groupby(["region", "kind"])["energy_mwh"]
        .sum()
        .unstack(fill_value=0.0)
        .rename(columns={"solar": "solar_mwh", "wind": "wind_mwh"})
    )

    for col in ["solar_mwh", "wind_mwh"]:
        if col not in split.columns:
            split[col] = 0.0

    split["solar_value"] = split["solar_mwh"] / 1_000_000.0
    split["wind_value"] = split["wind_mwh"] / 1_000_000.0
    split["total_value"] = split["solar_value"] + split["wind_value"]

    nonzero = split["total_value"] > 0
    split["solar_share_pct"] = 0.0
    split["wind_share_pct"] = 0.0
    split.loc[nonzero, "solar_share_pct"] = (
        100.0 * split.loc[nonzero, "solar_value"] / split.loc[nonzero, "total_value"]
    )
    split.loc[nonzero, "wind_share_pct"] = (
        100.0 * split.loc[nonzero, "wind_value"] / split.loc[nonzero, "total_value"]
    )

    return split[
        [
            "solar_value",
            "wind_value",
            "total_value",
            "solar_share_pct",
            "wind_share_pct",
        ]
    ]


def calculate_transmission_links_gw(
	network: pypsa.Network,
	region_names: set[str],
) -> pd.DataFrame:
	"""Compute optimal AC and DC inter-region capacities in GW."""
	ac_lines = (
		network.lines.loc[:, ["bus0", "bus1", "s_nom_opt"]]
		.rename(columns={"s_nom_opt": "capacity_mw"})
		.copy()
	)
	ac_lines["carrier"] = "AC"

	dc_links = network.links[network.links["carrier"].astype(str).str.upper().eq("DC")]
	dc_links = dc_links.loc[:, ["bus0", "bus1", "p_nom_opt"]].rename(
		columns={"p_nom_opt": "capacity_mw"}
	)
	dc_links["carrier"] = "DC"

	links = pd.concat([ac_lines, dc_links], ignore_index=True)
	links["r0"] = links["bus0"].astype(str).map(normalize_region_name)
	links["r1"] = links["bus1"].astype(str).map(normalize_region_name)
	links = links[
		links["r0"].isin(region_names)
		& links["r1"].isin(region_names)
		& (links["r0"] != links["r1"])
	].copy()

	pair = links.apply(lambda row: tuple(sorted((row["r0"], row["r1"]))), axis=1)
	links["r_from"] = pair.str[0]
	links["r_to"] = pair.str[1]
	links["capacity_gw"] = links["capacity_mw"] / 1000.0

	grouped = (
		links.groupby(["carrier", "r_from", "r_to"], as_index=False)["capacity_gw"]
		.sum()
		.sort_values(["carrier", "capacity_gw"], ascending=[True, False])
	)
	return grouped


def add_country_border_traces(fig: go.Figure, regions_gdf: gpd.GeoDataFrame) -> None:
	"""Add thick country boundaries on top of regional polygons."""
	country_gdf = regions_gdf.copy()
	country_gdf["country"] = country_gdf["name"].astype(str).str[:2]
	country_borders = country_gdf.dissolve(by="country")["geometry"].boundary

	show_legend = True
	for border_geom in country_borders:
		if border_geom.is_empty:
			continue

		line_geoms = list(border_geom.geoms) if border_geom.geom_type == "MultiLineString" else [border_geom]
		for line in line_geoms:
			coords = list(line.coords)
			if len(coords) < 2:
				continue

			lons = [xy[0] for xy in coords]
			lats = [xy[1] for xy in coords]
			fig.add_trace(
				go.Scattermapbox(
					lon=lons,
					lat=lats,
					mode="lines",
					line=dict(width=0.6, color="rgba(18,24,33,0.9)"),
					opacity=1.0,
					name="Country borders",
					legendgroup="country-borders",
					showlegend=show_legend,
					hoverinfo="skip",
				)
			)
			show_legend = False


def _circle_arc_points(
	lon_center: float,
	lat_center: float,
	radius_deg: float,
	start_angle_rad: float,
	end_angle_rad: float,
	n_points: int,
) -> tuple[list[float], list[float]]:
	"""Build arc coordinates around a center point with lon correction by latitude."""
	angles = [start_angle_rad + (end_angle_rad - start_angle_rad) * i / n_points for i in range(n_points + 1)]
	cos_lat = max(math.cos(math.radians(lat_center)), 0.2)
	lons = [lon_center + radius_deg * math.cos(a) / cos_lat for a in angles]
	lats = [lat_center + radius_deg * math.sin(a) for a in angles]
	return lons, lats


def _pie_wedge_polygon(
	lon_center: float,
	lat_center: float,
	radius_deg: float,
	start_angle_rad: float,
	end_angle_rad: float,
	n_points: int = 26,
) -> tuple[list[float], list[float]]:
	"""Return polygon coordinates for a pie wedge."""
	arc_lons, arc_lats = _circle_arc_points(
		lon_center, lat_center, radius_deg, start_angle_rad, end_angle_rad, n_points
	)
	lons = [lon_center] + arc_lons + [lon_center]
	lats = [lat_center] + arc_lats + [lat_center]
	return lons, lats


def add_region_pie_traces(
    fig: go.Figure,
    regions_gdf: gpd.GeoDataFrame,
    renewable_split: pd.DataFrame,
    pie_radius_deg: float,
    metric_unit_label: str,
) -> None:
    """Draw per-region solar/wind pie charts as topmost map traces."""
    region_points = regions_gdf.set_index("name").geometry.representative_point()
    split = renewable_split[renewable_split["total_value"] > 0].copy()
    show_legend = True
    for region, row in split.iterrows():
        if region not in region_points.index:
            continue

        point = region_points.loc[region]
        lon = float(point.x)
        lat = float(point.y)
        radius_deg = float(pie_radius_deg)

        wind_lons, wind_lats = _pie_wedge_polygon(
            lon, lat, radius_deg, -math.pi / 2.0, 3.0 * math.pi / 2.0
        )
        solar_share = float(row["solar_share_pct"]) / 100.0
        solar_end = -math.pi / 2.0 + (2.0 * math.pi * solar_share)
        solar_lons, solar_lats = _pie_wedge_polygon(
            lon, lat, radius_deg, -math.pi / 2.0, solar_end
        )
        outline_lons, outline_lats = _circle_arc_points(
            lon, lat, radius_deg, -math.pi / 2.0, 3.0 * math.pi / 2.0, n_points=72
        )

        # Wind base wedge
        fig.add_trace(
            go.Scattermapbox(
                lon=wind_lons,
                lat=wind_lats,
                mode="lines",
                line=dict(width=0.1, color="rgba(0,0,0,0)"),
                fill="toself",
                fillcolor="rgba(67,162,202,0.95)",
                hoverinfo="skip",
                showlegend=False,
            )
        )

        # Solar overlay wedge
        fig.add_trace(
            go.Scattermapbox(
                lon=solar_lons,
                lat=solar_lats,
                mode="lines",
                line=dict(width=0.1, color="rgba(0,0,0,0)"),
                fill="toself",
                fillcolor="rgba(246,201,69,0.95)",
                hoverinfo="skip",
                showlegend=False,
            )
        )

        # Pie outline
        fig.add_trace(
            go.Scattermapbox(
                lon=outline_lons + [outline_lons[0]],
                lat=outline_lats + [outline_lats[0]],
                mode="lines",
                line=dict(width=1.2, color="rgba(17,24,39,0.9)"),
                hoverinfo="skip",
                showlegend=False,
            )
        )

        fig.add_trace(
            go.Scattermapbox(
                lon=[lon],
                lat=[lat],
                mode="markers",
                marker=dict(size=12, opacity=0.01),
                name="Solar [yellow]/Wind [blue] split",
                legendgroup="pie-split",
                showlegend=show_legend,
                hovertemplate=(
                    f"<b>{region}</b><br>"
                    f"Solar: {row['solar_share_pct']:.1f}% ({row['solar_value']:.2f} {metric_unit_label})<br>"
                    f"Wind: {row['wind_share_pct']:.1f}% ({row['wind_value']:.2f} {metric_unit_label})<br>"
                    f"Total: {row['total_value']:.2f} {metric_unit_label}<extra></extra>"
                ),
            )
        )
        show_legend = False


def make_plot(
    regions_gdf: gpd.GeoDataFrame,
    renewable_values: pd.Series,
    renewable_split: pd.DataFrame,
    links_gw: pd.DataFrame,
    network: pypsa.Network,
    show_region_pie_charts: bool,
    pie_radius_deg: float,
    metric_unit_label: str,
    colorbar_title: str,
    plot_title: str,
) -> go.Figure:
    """Build presentation-style map with region fill and AC/DC links."""
    plot_gdf = regions_gdf.copy()
    plot_gdf["renewables_value"] = plot_gdf["name"].map(renewable_values).fillna(0.0)

    region_points = network.buses.loc[
        network.buses.index.intersection(plot_gdf["name"]), ["x", "y"]
    ].copy()

    geojson_dict = json.loads(plot_gdf.to_json())

    fig = go.Figure()
    fig.add_trace(
        go.Choroplethmapbox(
            geojson=geojson_dict,
            locations=plot_gdf["name"],
            z=plot_gdf["renewables_value"],
            featureidkey="properties.name",
            colorscale=[
                [0.0, "#f7fcf5"],
                [0.2, "#d9f0d3"],
                [0.45, "#a6dba0"],
                [0.7, "#5aae61"],
                [1.0, "#1b7837"],
            ],
            marker_line_width=0.9,
            marker_line_color="rgba(255,255,255,0.9)",
            colorbar=dict(
                title=colorbar_title,
                x=0.99,
                y=0.50,
                len=0.75,
                thickness=18,
                bgcolor="rgba(255,255,255,0.7)",
                tickfont=dict(size=20),
            ),
            hovertemplate=f"<b>%{{location}}</b><br>Renewables: %{{z:.2f}} {metric_unit_label}<extra></extra>",
            name="Regions",
            showscale=True,
        )
    )
    add_country_border_traces(fig, plot_gdf)

    if not links_gw.empty:
        links_plot = links_gw.copy()
        links_plot["width"] = scale_width(links_plot["capacity_gw"])

        ac_color = "#ff6f3c"
        dc_color = "#4cb5ae"

        shown = {"AC": False, "DC": False}
        for _, row in links_plot.iterrows():
            p0 = region_points.loc[row["r_from"]]
            p1 = region_points.loc[row["r_to"]]
            carrier = row["carrier"]
            color = ac_color if carrier == "AC" else dc_color

            fig.add_trace(
                go.Scattermapbox(
                    lon=[float(p0["x"]), float(p1["x"])],
                    lat=[float(p0["y"]), float(p1["y"])],
                    mode="lines",
                    line=dict(width=float(row["width"]), color=color),
                    opacity=0.85,
                    name=f"{carrier} links",
                    legendgroup=carrier,
                    showlegend=not shown[carrier],
                    hovertemplate=(
                        f"<b>{carrier}</b><br>"
                        f"{row['r_from']} -> {row['r_to']}<br>"
                        f"Capacity: {row['capacity_gw']:.2f} GW<extra></extra>"
                    ),
                )
            )
            shown[carrier] = True

    # Region label markers are subtle to keep the map readable while still informative.
    fig.add_trace(
        go.Scattermapbox(
            lon=region_points["x"],
            lat=region_points["y"],
            mode="markers",
            marker=dict(size=5, color="rgba(22,22,22,0.75)"),
            hovertemplate="<b>%{text}</b><extra></extra>",
            text=region_points.index,
            name="Region nodes",
            showlegend=False,
        )
    )

    # Add pie traces last so they remain visible above all previous layers/traces.
    if show_region_pie_charts:
        add_region_pie_traces(
            fig,
            regions_gdf=plot_gdf,
            renewable_split=renewable_split,
            pie_radius_deg=pie_radius_deg,
            metric_unit_label=metric_unit_label,
        )

    minx, miny, maxx, maxy = plot_gdf.total_bounds
    fig.update_layout(
        mapbox=dict(
            style="carto-positron",
            center={"lon": (minx + maxx) / 2.0, "lat": (miny + maxy) / 2.0},
            zoom=4.6,
        ),
        margin=dict(l=8, r=8, t=80, b=8),
        paper_bgcolor="#f2f5f8",
        plot_bgcolor="#f2f5f8",
        legend=dict(
            title="Overlays",
            orientation="h",
            yanchor="bottom",
            y=0.005,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.7)",
            font=dict(size=20),
        ),
        title={
            "text": plot_title,
            "x": 0.5,
            "xanchor": "center",
            "font": dict(size=25),
        },
    )
    return fig


def export_map_data_csv(
    regions_gdf: gpd.GeoDataFrame,
    renewable_split: pd.DataFrame,
    renewable_values: pd.Series,
    links_gw: pd.DataFrame,
    metric_unit_label: str,
    output_html: Path,
) -> Path:
    """Export regional and link data used by the map to a single CSV file."""
    output_csv = output_html.with_name(f"{output_html.stem}_data.csv")

    region_points = regions_gdf.set_index("name").geometry.representative_point()
    regions_table = pd.DataFrame(index=regions_gdf["name"].astype(str)).join(
        renewable_split, how="left"
    )
    regions_table["total_value"] = regions_table["total_value"].fillna(
        regions_table.index.to_series().map(renewable_values)
    )
    for col in [
        "solar_value",
        "wind_value",
        "total_value",
        "solar_share_pct",
        "wind_share_pct",
    ]:
        regions_table[col] = regions_table[col].fillna(0.0)

    regions_table["point_lon"] = regions_table.index.map(
        lambda region: float(region_points.loc[region].x)
    )
    regions_table["point_lat"] = regions_table.index.map(
        lambda region: float(region_points.loc[region].y)
    )
    regions_table = regions_table.reset_index(names="region")
    regions_table["record_type"] = "region"
    regions_table["metric_unit"] = metric_unit_label
    regions_table = regions_table[
        [
            "record_type",
            "metric_unit",
            "region",
            "point_lon",
            "point_lat",
            "solar_value",
            "wind_value",
            "total_value",
            "solar_share_pct",
            "wind_share_pct",
        ]
    ]

    links_table = links_gw.copy()
    links_table["record_type"] = "link"
    links_table["metric_unit"] = "GW"
    links_table = links_table.rename(
        columns={"r_from": "region_from", "r_to": "region_to"}
    )
    links_table = links_table[
        [
            "record_type",
            "metric_unit",
            "carrier",
            "region_from",
            "region_to",
            "capacity_gw",
        ]
    ]

    # Keep one CSV while preserving both region and link records.
    combined = pd.concat([regions_table, links_table], ignore_index=True, sort=False)
    combined.to_csv(output_csv, index=False)
    return output_csv


def main() -> None:
    print(f"[INFO] Loading network: {NETWORK_PATH}")
    network = pypsa.Network(NETWORK_PATH)

    regions_gdf = load_region_geometries(network)
    region_names = set(regions_gdf["name"].astype(str))

    if DISPLAY_METRIC == "capacity":
        renewable_split = calculate_renewable_split_by_region_gw(
            network,
            region_names,
            evaluate_austria_only=EVALUATE_AUSTRIA_ONLY,
        )
        metric_unit_label = "GW"
        colorbar_title = "Capacity [GW]"
        plot_title = (
            "<b>Optimal Wind+Solar Capacities and AC/DC Transmission Links</b>"
            "<br><sup>Net-zero: Austria 2040, all system 2050 | year 2050 | Installed capacities in GW</sup>"
        )
    elif DISPLAY_METRIC == "production":
        renewable_split = calculate_renewable_production_split_by_region_twh(
            network,
            region_names,
            evaluate_austria_only=EVALUATE_AUSTRIA_ONLY,
        )
        metric_unit_label = "TWh"
        colorbar_title = "Production [TWh]"
        plot_title = (
            "<b>Modeled Wind+Solar Electricity and AC/DC Transmission Links</b>"
            "<br><sup>Net-zero: Austria 2040, all system 2050 | year 2050 | Produced electricity over modeled period in TWh</sup>"
        )
    else:
        raise ValueError("DISPLAY_METRIC must be either 'capacity' or 'production'")

    renewable_values = renewable_split["total_value"]
    links_gw = calculate_transmission_links_gw(network, region_names)

    if EVALUATE_AUSTRIA_ONLY:
        print("[INFO] Evaluation mode: AUSTRIA ONLY (regions starting with 'AT')")
    else:
        print("[INFO] Evaluation mode: ALL REGIONS")
    print(f"[INFO] Display metric: {DISPLAY_METRIC.upper()} ({metric_unit_label})")

    print(f"[INFO] Regions with polygon geometry: {len(regions_gdf)}")
    print(
        f"[INFO] Regions with non-zero wind+solar value: {(renewable_values > 0).sum()}"
    )
    print(f"[INFO] AC/DC inter-region links plotted: {len(links_gw)}")
    print(f"[INFO] Pie-chart overlay enabled: {SHOW_REGION_PIE_CHARTS}")

    fig = make_plot(
        regions_gdf,
        renewable_values,
        renewable_split,
        links_gw,
        network,
        show_region_pie_charts=SHOW_REGION_PIE_CHARTS,
        pie_radius_deg=PIE_RADIUS_DEG,
        metric_unit_label=metric_unit_label,
        colorbar_title=colorbar_title,
        plot_title=plot_title,
    )
    fig.write_html(OUTPUT_HTML, include_plotlyjs="cdn")
    output_csv = export_map_data_csv(
        regions_gdf=regions_gdf,
        renewable_split=renewable_split,
        renewable_values=renewable_values,
        links_gw=links_gw,
        metric_unit_label=metric_unit_label,
        output_html=OUTPUT_HTML,
    )
    print(f"[DONE] Wrote interactive map to: {OUTPUT_HTML}")
    print(f"[DONE] Wrote map data CSV to: {output_csv}")


if __name__ == "__main__":
	main()
