from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import pypsa

# ---------------------------------------------------------------------------
# Configuration - set values directly in this script (no CLI parser)
# ---------------------------------------------------------------------------

NETWORK_PATH = Path("/home/maxnutz/Documents/evaluations/base_s_adm__none_2025.nc")
REGIONS_PATH = Path("resources/regions_onshore.geojson")
FALLBACK_REGIONS_PATH = Path("resources/regions_onshore_base_s_adm.geojson")

OUTPUT_HTML = Path("outputs/brownfield_infrastructure_map.html")
OUTPUT_STATIC = Path("outputs/brownfield_infrastructure_map.svg")

# Set to two-letter country code like "AT" for country focus, or None for all.
COUNTRY_ONLY = None

# Toggle component families.
PLOT_LINES = True
PLOT_LINKS = True
SHOW_MAJOR_CITIES = False

# Filter carriers to display. Set to None to show all, or provide a list/set of carrier names.
# Example: CARRIERS_FILTER = {"AC", "DC", "H2 pipeline"}
CARRIERS_FILTER = None

# Visual tuning.
MAP_STYLE = "carto-positron"
PAPER_BG_COLOR = "rgba(238,242,247,0.27)"
PLOT_BG_COLOR = "rgba(238,242,247,0.27)"
EDGE_OPACITY = 0.42
MIN_WIDTH = 1.8
MAX_WIDTH = 50.0  # 80.0
WIDTH_BUCKETS = 10
REGION_BORDER_COLOR = "rgba(100,116,139,0.4)"
REGION_BORDER_WIDTH = 0.5
COUNTRY_BORDER_COLOR = "rgba(24,36,58,0.9)"
COUNTRY_BORDER_WIDTH = 0.85
CITY_MARKER_COLOR = "rgba(20,20,25,0.88)"
CITY_TEXT_COLOR = "rgba(16,22,32,0.95)"

# Routing/overlap reduction.
CURVE_SAMPLES = 24
PAIR_CURVATURE_FACTOR = 0.11
CARRIER_CURVATURE_FACTOR = 0.2

TITLE = "<b>Brownfield Infrastructure 2025</b>" "<br><sup>PyPSA energy system</sup>"

COLOR_DICT = {
    "AC": "#3964F5",
    "DC": "#480058",
    "gas pipeline": "#FFA213",
    "gas pipeline new": "#B47C14",
    "H2 pipeline retrofitted": "#35BFA0",
    "H2 pipeline": "#6DEEC9",
    "solid biomass transport": "#8DED71",
    "municipal solid waste transport": "#5C6E5F",
    "CO2 pipeline": "#7f7f7f",
}

EXCLUDED_CARRIERS = {
	"solid biomass transport",
	"municipal solid waste transport",
}

MAJOR_CITIES = [
	{"name": "Vienna", "lat": 48.2082, "lon": 16.3738, "country": "AT"},
	{"name": "Berlin", "lat": 52.52, "lon": 13.405, "country": "DE"},
	{"name": "Paris", "lat": 48.8566, "lon": 2.3522, "country": "FR"},
	{"name": "Rome", "lat": 41.9028, "lon": 12.4964, "country": "IT"},
	{"name": "Madrid", "lat": 40.4168, "lon": -3.7038, "country": "ES"},
	{"name": "Warsaw", "lat": 52.2297, "lon": 21.0122, "country": "PL"},
	{"name": "Prague", "lat": 50.0755, "lon": 14.4378, "country": "CZ"},
	{"name": "Budapest", "lat": 47.4979, "lon": 19.0402, "country": "HU"},
	{"name": "Brussels", "lat": 50.8503, "lon": 4.3517, "country": "BE"},
	{"name": "Amsterdam", "lat": 52.3676, "lon": 4.9041, "country": "NL"},
	{"name": "Copenhagen", "lat": 55.6761, "lon": 12.5683, "country": "DK"},
	{"name": "Stockholm", "lat": 59.3293, "lon": 18.0686, "country": "SE"},
	{"name": "Oslo", "lat": 59.9139, "lon": 10.7522, "country": "NO"},
	{"name": "Helsinki", "lat": 60.1699, "lon": 24.9384, "country": "FI"},
	{"name": "Dublin", "lat": 53.3498, "lon": -6.2603, "country": "IE"},
	{"name": "Lisbon", "lat": 38.7223, "lon": -9.1393, "country": "PT"},
	{"name": "Athens", "lat": 37.9838, "lon": 23.7275, "country": "GR"},
	{"name": "Zurich", "lat": 47.3769, "lon": 8.5417, "country": "CH"},
	{"name": "Bucharest", "lat": 44.4268, "lon": 26.1025, "country": "RO"},
	{"name": "Belgrade", "lat": 44.7866, "lon": 20.4489, "country": "RS"},
	{"name": "Sofia", "lat": 42.6977, "lon": 23.3219, "country": "BG"},
	{"name": "Zagreb", "lat": 45.815, "lon": 15.9819, "country": "HR"},
	{"name": "Ljubljana", "lat": 46.0569, "lon": 14.5058, "country": "SI"},
	{"name": "Bratislava", "lat": 48.1486, "lon": 17.1077, "country": "SK"},
]


def normalize_region_name(value: object) -> str:
	if value is None or pd.isna(value):
		return ""
	return str(value).removesuffix(" low voltage").strip()


def infer_country(name: str) -> str:
	normalized = normalize_region_name(name)
	return normalized[:2] if normalized else ""


def load_regions(path: Path, fallback_path: Path, network: pypsa.Network) -> gpd.GeoDataFrame:
	if not path.exists():
		raise FileNotFoundError(f"Regions file not found: {path}")

	gdf = gpd.read_file(path)
	if "name" not in gdf.columns:
		raise ValueError(f"Regions file requires a 'name' column: {path}")
	if gdf.crs is None:
		gdf = gdf.set_crs("EPSG:4326")
	else:
		gdf = gdf.to_crs("EPSG:4326")

	gdf["name"] = gdf["name"].astype(str)
	if "country" not in gdf.columns:
		gdf["country"] = gdf["name"].map(infer_country)
	else:
		gdf["country"] = gdf["country"].astype(str)

	# If region naming does not match network location naming, use fallback.
	network_locations = {
		normalize_region_name(value)
		for value in network.buses.location.dropna().tolist()
	}
	network_locations.discard("")
	overlap = len(set(gdf["name"]) & network_locations)

	if overlap == 0 and fallback_path.exists():
		print(f"[INFO] No overlap with {path}; using fallback {fallback_path}")
		fallback = gpd.read_file(fallback_path)
		if "name" not in fallback.columns:
			raise ValueError(f"Fallback regions file requires a 'name' column: {fallback_path}")
		if fallback.crs is None:
			fallback = fallback.set_crs("EPSG:4326")
		else:
			fallback = fallback.to_crs("EPSG:4326")
		fallback["name"] = fallback["name"].astype(str)
		if "country" not in fallback.columns:
			fallback["country"] = fallback["name"].map(infer_country)
		else:
			fallback["country"] = fallback["country"].astype(str)
		gdf = fallback

	return gdf[["name", "country", "geometry"]].copy()


def filter_regions(regions: gpd.GeoDataFrame, country_only: str | None) -> gpd.GeoDataFrame:
	if not country_only:
		return regions.copy()

	country = country_only.upper()
	filtered = regions[regions["country"].str.upper() == country].copy()
	if filtered.empty:
		raise ValueError(f"No regions found for COUNTRY_ONLY={country_only}.")
	return filtered


def region_centers(regions: gpd.GeoDataFrame) -> pd.DataFrame:
	centers = regions.set_index("name").geometry.representative_point()
	return pd.DataFrame({"lon": centers.x, "lat": centers.y})


def edge_width(value: float, min_v: float, max_v: float, min_w: float, max_w: float) -> float:
	if math.isclose(min_v, max_v):
		return (min_w + max_w) / 2.0
	scaled = min_w + (value - min_v) * (max_w - min_w) / (max_v - min_v)
	return float(max(min_w, min(max_w, scaled)))


def generate_color_map(carriers: list[str]) -> dict[str, str]:
    palette = [
        "#06b6d4",
        "#8b5cf6",
        "#f43f5e",
        "#84cc16",
        "#f59e0b",
        "#3b82f6",
        "#10b981",
        "#ef4444",
        "#14b8a6",
        "#e879f9",
        "#f97316",
        "#22c55e",
    ]
    unique = sorted({carrier for carrier in carriers if carrier})
    result: dict[str, str] = {}
    index = 0
    for carrier in unique:
        if carrier in COLOR_DICT:
            result[carrier] = COLOR_DICT[carrier]
        else:
            result[carrier] = palette[index % len(palette)]
            index += 1
    return result


def extract_geographical_infrastructure(nw: pypsa.Network) -> pd.DataFrame:
    """
    Extract geographical infrastructure (links and lines connecting different regions)
    using PyPSA statistics for efficient aggregation.
    """
    # Get aggregated capacities for all links and lines grouped by bus0, bus1, carrier
    all_links = (
        nw.statistics.installed_capacity(
            components=["Link", "Line"], groupby=["bus0", "bus1", "carrier"]
        )
        .to_frame(name="capacity_mw")
        .reset_index()
    )

    # Map bus locations WITHOUT normalizing yet - keep original location names
    all_links["location_bus0"] = all_links["bus0"].map(nw.buses.location)
    all_links["location_bus1"] = all_links["bus1"].map(nw.buses.location)

    # Filter to only geographical links (different locations, excluding EU)
    geographical_links = all_links[
        (all_links["location_bus0"] != all_links["location_bus1"])
        & (all_links["location_bus0"] != "EU")
        & (all_links["location_bus1"] != "EU")
    ].copy()

    if geographical_links.empty:
        return pd.DataFrame(
            columns=[
                "bus0",
                "bus1",
                "carrier",
                "capacity_mw",
                "from_region",
                "to_region",
                "component",
            ]
        )

    # Use location as region name directly (don't normalize)
    geographical_links["from_region"] = geographical_links["location_bus0"]
    geographical_links["to_region"] = geographical_links["location_bus1"]
    geographical_links["carrier"] = geographical_links["carrier"].astype(str)

    # Determine component type (Link or Line) by checking original components
    # Create a set of (bus0, bus1) pairs that exist as links
    link_pairs = set(zip(nw.links["bus0"], nw.links["bus1"]))

    def get_component_type(row):
        bus_pair = (row["bus0"], row["bus1"])
        return "link" if bus_pair in link_pairs else "line"

    geographical_links["component"] = geographical_links.apply(
        get_component_type, axis=1
    )

    # Select and reorder columns to match expected format
    return geographical_links[
        [
            "bus0",
            "bus1",
            "carrier",
            "capacity_mw",
            "from_region",
            "to_region",
            "component",
        ]
    ]


def filter_infrastructure_by_regions(
	components: pd.DataFrame,
	valid_regions: set[str],
	country_only: str | None,
	carriers_filter: set[str] | None = None,
) -> pd.DataFrame:
    if components.empty:
        return components

    # Create a function to check if a region is valid
    # It handles both direct matches and prefix matches (e.g., 'FR' matches 'FR0', 'FR1')
    def is_valid_region(region):
        if region in valid_regions:
            return True
        # Check if any valid region starts with this region (e.g., 'FR' matches 'FR0', 'FR1')
        return any(vr.startswith(region) for vr in valid_regions)

    filtered = components[
        components["from_region"].apply(is_valid_region)
        & components["to_region"].apply(is_valid_region)
        & components["from_region"].ne(components["to_region"])
        & components["capacity_mw"].gt(0.0)
    ].copy()

    if country_only:
        country = country_only.upper()
        filtered = filtered[
            filtered["from_region"].str.startswith(country)
            & filtered["to_region"].str.startswith(country)
        ].copy()

    if "carrier" in filtered.columns:
        filtered = filtered[~filtered["carrier"].isin(EXCLUDED_CARRIERS)].copy()
        # Apply user-defined carrier filter if specified
        if carriers_filter is not None:
            filtered = filtered[filtered["carrier"].isin(carriers_filter)].copy()
    return filtered


def curved_path(
	lon0: float,
	lat0: float,
	lon1: float,
	lat1: float,
	curvature: float,
	samples: int,
) -> tuple[list[float], list[float]]:
	if lon0 == lon1 and lat0 == lat1:
		return [lon0, lon1], [lat0, lat1]

	mean_lat = math.radians((lat0 + lat1) / 2.0)
	lon_scale = max(math.cos(mean_lat), 0.2)
	dx = (lon1 - lon0) * lon_scale
	dy = lat1 - lat0
	length = math.hypot(dx, dy)
	if length == 0:
		return [lon0, lon1], [lat0, lat1]

	nx = -dy / length
	ny = dx / length
	ctrl_lon = (lon0 + lon1) / 2.0 + (nx * curvature) / lon_scale
	ctrl_lat = (lat0 + lat1) / 2.0 + ny * curvature

	lons: list[float] = []
	lats: list[float] = []
	for i in range(samples + 1):
		t = i / samples
		lon = (1 - t) ** 2 * lon0 + 2 * (1 - t) * t * ctrl_lon + t**2 * lon1
		lat = (1 - t) ** 2 * lat0 + 2 * (1 - t) * t * ctrl_lat + t**2 * lat1
		lons.append(lon)
		lats.append(lat)
	return lons, lats


def build_infrastructure_table(
	nw: pypsa.Network,
	centers: pd.DataFrame,
	valid_regions: set[str],
	country_only: str | None,
	carriers_filter: set[str] | None = None,
) -> pd.DataFrame:
    # Extract geographical infrastructure using PyPSA statistics (includes both links and lines)
    table = extract_geographical_infrastructure(nw)

    if table.empty:
        return pd.DataFrame()

    # Filter to only requested component types
    if PLOT_LINKS and PLOT_LINES:
        pass  # Keep both links and lines
    elif PLOT_LINKS:
        table = table[table["component"] == "link"].copy()
    elif PLOT_LINES:
        table = table[table["component"] == "line"].copy()
    else:
        return pd.DataFrame()

    if table.empty:
        return pd.DataFrame()

    table = filter_infrastructure_by_regions(
        table, valid_regions, country_only, carriers_filter
    )
    if table.empty:
        return table

    # Create a mapping from network region codes (e.g., 'FR') to GeoJSON region names (e.g., 'FR0')
    # For aggregated regions, use the first matching subdivided region
    network_to_geojson = {}
    for region in table["from_region"].unique():
        if region in centers.index:
            network_to_geojson[region] = region
        else:
            # Find first matching region that starts with this code
            matching = [r for r in centers.index if r.startswith(region)]
            if matching:
                network_to_geojson[region] = sorted(matching)[0]

    # Apply the mapping
    table["mapped_from"] = table["from_region"].map(network_to_geojson)
    table["mapped_to"] = table["to_region"].map(network_to_geojson)

    # Drop rows where mapping failed
    table = table.dropna(subset=["mapped_from", "mapped_to"]).copy()

    table["from_lon"] = table["mapped_from"].map(centers["lon"])
    table["from_lat"] = table["mapped_from"].map(centers["lat"])
    table["to_lon"] = table["mapped_to"].map(centers["lon"])
    table["to_lat"] = table["mapped_to"].map(centers["lat"])
    table = table.dropna(subset=["from_lon", "from_lat", "to_lon", "to_lat"]).copy()

    # Sum capacities for all connections between same region pair and carrier
    table = table.groupby(
        ["from_region", "to_region", "carrier"],
        as_index=False,
    ).agg(
        {
            "component": "first",
            "bus0": "first",
            "bus1": "first",
            "capacity_mw": "sum",
            "from_lon": "first",
            "from_lat": "first",
            "to_lon": "first",
            "to_lat": "first",
        }
    )

    table["pair_key"] = (
        table["from_region"].where(
            table["from_region"] <= table["to_region"],
            table["to_region"],
        )
        + "|"
        + table["to_region"].where(
            table["from_region"] <= table["to_region"],
            table["from_region"],
        )
    )

    table = table.sort_values(
        ["pair_key", "carrier", "capacity_mw"],
        ascending=[True, True, False],
        kind="stable",
    ).reset_index(drop=True)

    min_cap = float(table["capacity_mw"].min())
    max_cap = float(table["capacity_mw"].max())
    table["width_px"] = table["capacity_mw"].map(
        lambda cap: edge_width(float(cap), min_cap, max_cap, MIN_WIDTH, MAX_WIDTH)
    )

    # if WIDTH_BUCKETS <= 1:
    #     table["width_bucket"] = 0
    #     table["width_bucket_px"] = (MIN_WIDTH + MAX_WIDTH) / 2.0
    # else:
    #     scaled = (table["width_px"] - MIN_WIDTH) / (MAX_WIDTH - MIN_WIDTH)
    #     table["width_bucket"] = (scaled * (WIDTH_BUCKETS - 1)).round().astype(int)
    #     table["width_bucket_px"] = MIN_WIDTH + (
    #         table["width_bucket"] * (MAX_WIDTH - MIN_WIDTH) / (WIDTH_BUCKETS - 1)
    #     )

    max_gw = table["capacity_mw"].max()
    table["width_bucket"] = (table["capacity_mw"] / max_gw * MAX_WIDTH) + MIN_WIDTH

    table["width_bucket_px"] = table["width_bucket"]

    table["curvature"] = 0.0
    for pair_key, pair_index in table.groupby("pair_key").groups.items():
        idx = list(pair_index)
        n = len(idx)
        if n == 1:
            table.loc[idx, "curvature"] = 0.0
            continue

        row = table.loc[idx[0]]
        mean_lat = math.radians((float(row["from_lat"]) + float(row["to_lat"])) / 2.0)
        lon_scale = max(math.cos(mean_lat), 0.2)
        dist = math.hypot(
            (float(row["to_lon"]) - float(row["from_lon"])) * lon_scale,
            float(row["to_lat"]) - float(row["from_lat"]),
        )
        base = max(0.025, dist * PAIR_CURVATURE_FACTOR)
        offsets = [
            ((k - (n - 1) / 2.0) * base * CARRIER_CURVATURE_FACTOR * 10.0)
            for k in range(n)
        ]
        table.loc[idx, "curvature"] = offsets

    return table

def add_region_layer(fig: go.Figure, regions: gpd.GeoDataFrame) -> None:
    # Simplify geometries to reduce GeoJSON size while preserving visual appearance.
    simplified = regions.copy()
    simplified["geometry"] = simplified.geometry.simplify(
        tolerance=0.01, preserve_topology=True
    )
    geojson_dict = json.loads(simplified.to_json())
    regions_sorted = simplified.sort_values("name")
    fig.add_trace(
        go.Choroplethmapbox(
            geojson=geojson_dict,
            featureidkey="properties.name",
            locations=regions_sorted["name"],
            z=[1.0] * len(regions_sorted),
            colorscale=[
                [0.0, "rgba(220,232,246,0.32)"],
                [1.0, "rgba(220,232,246,0.32)"],
            ],
            marker_line_width=REGION_BORDER_WIDTH,
            marker_line_color=REGION_BORDER_COLOR,
            showscale=False,
            hoverinfo="skip",
            name="Regions",
        )
    )


def add_country_borders(fig: go.Figure, regions: gpd.GeoDataFrame) -> None:
	# Dissolve by country and simplify before extracting borders.
	country_geoms = regions.dissolve(by="country")
	country_geoms["geometry"] = country_geoms.geometry.simplify(tolerance=0.01, preserve_topology=True)
	borders = country_geoms.geometry.boundary

	# Collect all segments into a single trace, separated by None.
	all_lons: list[float | None] = []
	all_lats: list[float | None] = []
	for border in borders:
		if border.is_empty:
			continue
		lines = list(border.geoms) if border.geom_type == "MultiLineString" else [border]
		for line in lines:
			coords = list(line.coords)
			if len(coords) < 2:
				continue
			all_lons.extend(c[0] for c in coords)
			all_lons.append(None)
			all_lats.extend(c[1] for c in coords)
			all_lats.append(None)

	if all_lons:
		fig.add_trace(
			go.Scattermapbox(
				lon=all_lons,
				lat=all_lats,
				mode="lines",
				line={"width": COUNTRY_BORDER_WIDTH, "color": COUNTRY_BORDER_COLOR},
				hoverinfo="skip",
				name="Country borders",
				legendgroup="country-borders",
				showlegend=False,
			)
		)


def add_city_layer(fig: go.Figure, country_only: str | None) -> None:
	if not SHOW_MAJOR_CITIES:
		return

	cities = MAJOR_CITIES
	if country_only:
		cities = [c for c in MAJOR_CITIES if c["country"].upper() == country_only.upper()]
	if not cities:
		return

	fig.add_trace(
		go.Scattermapbox(
			lon=[c["lon"] for c in cities],
			lat=[c["lat"] for c in cities],
			mode="markers+text",
			text=[c["name"] for c in cities],
			textposition="top right",
			textfont={"size": 12, "color": CITY_TEXT_COLOR},
			marker={"size": 7.0, "color": CITY_MARKER_COLOR},
			hovertemplate="<b>%{text}</b><extra></extra>",
			name="Major cities",
		)
	)


def add_infrastructure_layers(fig: go.Figure, infra: pd.DataFrame, color_map: dict[str, str]) -> None:
    # Plot links first, then lines. Within each component type, group by carrier.
    # Hover markers are placed at mid-points so capacity info is accessible.
    for component_type in ["link", "line"]:
        component_data = infra[infra["component"] == component_type]

        for carrier, group in component_data.groupby("carrier", sort=False):
            all_lon: list[float | None] = []
            all_lat: list[float | None] = []
            hover_lon: list[float] = []
            hover_lat: list[float] = []
            hover_text: list[str] = []

            for row in group.itertuples(index=False):
                lon, lat = curved_path(
                    float(row.from_lon),
                    float(row.from_lat),
                    float(row.to_lon),
                    float(row.to_lat),
                    float(row.curvature),
                    CURVE_SAMPLES,
                )
                all_lon.extend(lon)
                all_lon.append(None)
                all_lat.extend(lat)
                all_lat.append(None)
                mid = len(lon) // 2
                hover_lon.append(lon[mid])
                hover_lat.append(lat[mid])
                cap_gw = float(row.capacity_mw) / 1000.0
                hover_text.append(
                    f"<b>{row.from_region} → {row.to_region}</b>"
                    f"<br>Carrier: {carrier}"
                    f"<br>Capacity: {cap_gw:.2f} GW"
                )

            # Representative line width: median of the bucket widths for this carrier.
            # med_width = float(group["width_bucket_px"].median())
            color = color_map.get(str(carrier), "#334155")
            isfirst = True
            for index, line in group.iterrows():
                fig.add_trace(
                    go.Scattermapbox(
                        lon=[line.from_lon, line.to_lon],
                        lat=[line.from_lat, line.to_lat],
                        mode="lines",
                        line={"width": line.width_bucket_px, "color": color},
                        opacity=EDGE_OPACITY,
                        name=str(carrier),
                        legendgroup=f"carrier::{carrier}",
                        showlegend=isfirst,
                        hoverinfo="skip",
                    )
                )
                isfirst = False

            # Invisible hover markers at segment mid-points (no extra visual clutter).
            fig.add_trace(
                go.Scattermapbox(
                    lon=hover_lon,
                    lat=hover_lat,
                    mode="markers",
                    marker={"size": 8, "opacity": 0.0, "color": color},
                    text=hover_text,
                    hovertemplate="%{text}<extra></extra>",
                    name=str(carrier),
                    legendgroup=f"carrier::{carrier}",
                    showlegend=False,
                )
            )


def add_capacity_scale_legend(fig: go.Figure, infra: pd.DataFrame) -> None:
	if infra.empty:
		return
	min_cap = float(infra["capacity_mw"].min())
	max_cap = float(infra["capacity_mw"].max())
	samples = [
		max(min_cap, min(max_cap, q))
		for q in [
			min_cap,
			min_cap + (max_cap - min_cap) * 0.4,
			min_cap + (max_cap - min_cap) * 0.8,
		]
	]
	labels = [f"{s/1000.0:.2f} GW" for s in samples]

	for sample, label in zip(samples, labels):
		fig.add_trace(
			go.Scattermapbox(
				lon=[None],
				lat=[None],
				mode="lines",
				line={"width": edge_width(sample, min_cap, max_cap, MIN_WIDTH, MAX_WIDTH), "color": "#0f172a"},
				name=f"Capacity scale: {label}",
				legendgroup="capacity-scale",
				showlegend=True,
				hoverinfo="skip",
			)
		)


def build_figure(regions: gpd.GeoDataFrame, infra: pd.DataFrame, country_only: str | None) -> go.Figure:
    fig = go.Figure()

    color_map = (
        generate_color_map(infra["carrier"].astype(str).tolist())
        if not infra.empty
        else {}
    )
    add_region_layer(fig, regions)
    add_country_borders(fig, regions)
    if not infra.empty:
        add_infrastructure_layers(fig, infra, color_map)
        add_capacity_scale_legend(fig, infra)
    add_city_layer(fig, country_only)

    minx, miny, maxx, maxy = regions.total_bounds
    center = {"lon": float((minx + maxx) / 2.0), "lat": float((miny + maxy) / 2.0)}

    lon_span = max(maxx - minx, 1.0)
    zoom = 5.2 - math.log(lon_span, 2)
    zoom = max(3.2, min(6.8, zoom))

    fig.update_layout(
        title={"text": TITLE, "x": 0.5, "xanchor": "center", "font": {"size": 28}},
        mapbox={"style": MAP_STYLE, "center": center, "zoom": zoom},
        paper_bgcolor=PAPER_BG_COLOR,
        plot_bgcolor=PLOT_BG_COLOR,
        margin={"l": 6, "r": 6, "t": 90, "b": 6},
        legend={
            "title": {"text": "Carriers", "font": {"size": 16}},
            "bgcolor": "rgba(255,255,255,0.82)",
            "font": {"size": 13},
            "x": 0.01,
            "y": 0.99,
            "xanchor": "left",
            "yanchor": "top",
            "bordercolor": "rgba(148,163,184,0.35)",
            "borderwidth": 1,
        },
    )

    return fig


def export_static_matplotlib(
	regions: gpd.GeoDataFrame,
	infra: pd.DataFrame,
	color_map: dict[str, str],
	output_static: Path,
	country_only: str | None,
) -> None:
	fig, ax = plt.subplots(figsize=(16, 11), constrained_layout=True)
	fig.patch.set_facecolor(PAPER_BG_COLOR)
	ax.set_facecolor(PLOT_BG_COLOR)

	regions.plot(
		ax=ax,
		facecolor="#dce8f6",
		edgecolor="#f7fafc",
		linewidth=0.5,
		alpha=0.40,
		zorder=1,
	)
	regions.dissolve(by="country").geometry.boundary.plot(
		ax=ax,
		color="#1e293b",
		linewidth=1.0,
		alpha=0.9,
		zorder=2,
	)

	for _, row in infra.iterrows():
		lons, lats = curved_path(
			float(row["from_lon"]),
			float(row["from_lat"]),
			float(row["to_lon"]),
			float(row["to_lat"]),
			float(row["curvature"]),
			CURVE_SAMPLES,
		)
		ax.plot(
			lons,
			lats,
			color=color_map.get(str(row["carrier"]), "#334155"),
			linewidth=float(row["width_px"]) * 0.7,
			alpha=EDGE_OPACITY,
			solid_capstyle="round",
			zorder=3,
		)

	cities = MAJOR_CITIES
	if country_only:
		cities = [c for c in MAJOR_CITIES if c["country"].upper() == country_only.upper()]
	if SHOW_MAJOR_CITIES and cities:
		xs = [c["lon"] for c in cities]
		ys = [c["lat"] for c in cities]
		ax.scatter(xs, ys, s=18, c="#111827", zorder=4)
		for city in cities:
			ax.text(
				city["lon"] + 0.12,
				city["lat"] + 0.09,
				city["name"],
				fontsize=8,
				color="#0f172a",
				zorder=5,
			)

	minx, miny, maxx, maxy = regions.total_bounds
	pad_x = max((maxx - minx) * 0.03, 0.2)
	pad_y = max((maxy - miny) * 0.03, 0.2)
	ax.set_xlim(minx - pad_x, maxx + pad_x)
	ax.set_ylim(miny - pad_y, maxy + pad_y)
	ax.set_aspect("equal", adjustable="box")
	ax.axis("off")
	ax.set_title("Brownfield Inter-Regional Infrastructure", fontsize=22, pad=20)

	output_static.parent.mkdir(parents=True, exist_ok=True)
	fig.savefig(output_static, dpi=220, bbox_inches="tight")
	plt.close(fig)
	print(f"[DONE] Static fallback export (matplotlib): {output_static}")


def export_figure(
	fig: go.Figure,
	output_html: Path,
	output_static: Path,
	regions: gpd.GeoDataFrame,
	infra: pd.DataFrame,
	color_map: dict[str, str],
	country_only: str | None,
) -> None:
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_static.parent.mkdir(parents=True, exist_ok=True)

    fig.write_html(
        output_html,
        include_plotlyjs="cdn",
        config={"scrollZoom": True, "displayModeBar": True},
    )
    print(f"[DONE] HTML export: {output_html}")

    try:
        fig.write_image(output_static)
        print(f"[DONE] Static export: {output_static}")
    except Exception as exc:
        try:
            export_static_matplotlib(
                regions, infra, color_map, output_static, country_only
            )
            print(
                f"[WARN] Plotly static export failed, used matplotlib fallback. Error: {exc}"
            )
        except Exception as fallback_exc:
            print("[WARN] Static export failed in both Plotly and matplotlib fallback.")
            print(f"[WARN] Plotly export error: {exc}")
            print(f"[WARN] Matplotlib fallback error: {fallback_exc}")


def main() -> None:
	print(f"[INFO] Loading network: {NETWORK_PATH}")
	nw = pypsa.Network(NETWORK_PATH)

	regions = load_regions(REGIONS_PATH, FALLBACK_REGIONS_PATH, nw)
	regions = filter_regions(regions, COUNTRY_ONLY)
	centers = region_centers(regions)
	valid_regions = set(centers.index.astype(str))

	# Convert CARRIERS_FILTER to set if provided
	carriers_filter_set = set(CARRIERS_FILTER) if CARRIERS_FILTER is not None else None
	
	infra = build_infrastructure_table(nw, centers, valid_regions, COUNTRY_ONLY, carriers_filter_set)
	n_links = int((infra["component"] == "link").sum()) if not infra.empty else 0
	n_lines = int((infra["component"] == "line").sum()) if not infra.empty else 0

	print(f"[INFO] Regions plotted: {len(regions)}")
	print(f"[INFO] Inter-region links plotted: {n_links}")
	print(f"[INFO] Inter-region lines plotted: {n_lines}")
	print(f"[INFO] Carriers shown: {infra['carrier'].nunique() if not infra.empty else 0}")
	if CARRIERS_FILTER is not None:
		print(f"[INFO] Carriers filter applied: {CARRIERS_FILTER}")

	if infra.empty:
		raise ValueError("No inter-region infrastructure found after filtering.")

	color_map = generate_color_map(infra["carrier"].astype(str).tolist())
	fig = build_figure(regions, infra, COUNTRY_ONLY)
	export_figure(fig, OUTPUT_HTML, OUTPUT_STATIC, regions, infra, color_map, COUNTRY_ONLY)


if __name__ == "__main__":
	main()
