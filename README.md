# pypsa-evaluations
This repository is a collection of various specific evaluations of pypsa-networks

## Renewables Usage Visualization

### Overview

This script generates an interactive map visualization of optimal wind and solar capacities across geographic regions, along with AC/DC transmission links. It analyzes a PyPSA network model and produces a Plotly-based HTML map showing:

- **Regional renewable capacities**: Choropleth coloring indicates total wind + solar capacity (GW) per region
- **Transmission links**: AC and DC inter-region connections scaled by capacity
- **Country borders**: Overlaid for geographic context
- **Optional pie charts**: Regional breakdown of solar vs. wind generation (togglable)

### Usage

```bash
python renewables_usage.py
```

The script reads from the network file specified by `NETWORK_PATH` and outputs an interactive HTML map to `OUTPUT_HTML`.

### Configuration

The script includes several toggles at the top of the file:

| Setting | Description |
|---------|------------|
| `NETWORK_PATH` | Path to the PyPSA network file (.nc format) |
| `FALLBACK_REGIONS_PATH` | Path to region geometries (GeoJSON) for map polygons |
| `OUTPUT_HTML` | Output file path for the generated interactive map |
| `EVALUATE_AUSTRIA_ONLY` | When `True`, only evaluates regions with names starting with "AT" |
| `SHOW_REGION_PIE_CHARTS` | When `True`, displays pie charts showing solar/wind split per region |
| `PIE_RADIUS_DEG` | Size of pie chart overlays (in map degrees) |

### Output

The script generates an interactive HTML map (`renewables_links_map.html`) with:

- **Hover information**: Click on regions or links to see detailed capacity data
- **Interactive legend**: Toggle overlays on/off
- **Zoom and pan**: Explore different map areas
- **Responsive design**: Works in modern web browsers

### Requirements

- `pypsa`: Network analysis library
- `geopandas`: Geospatial data handling
- `pandas`: Data manipulation
- `plotly`: Interactive visualization
- `shapely`: Geometry operations (via geopandas)

### Example Output

<img src="pngs/renewable_usagemap.png" alt="Renewable usage map" width="600" />

The generated map displays:
- Wind+solar capacity scaled by region color intensity
- AC transmission links in orange, DC links in teal
- Wind (blue) and solar (yellow) pie chart splits at each region (if enabled)
- Informative hover tooltips with capacity values in GW

---

