import os
import pandas as pd
import pypsa
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

NETWORKS_FOLDER = "pypsa-validation_processing/resources/AT_KN2040/networks/"
SINGLE_NETWORK_FILE = "pypsa-validation_processing/resources/AT_KN2040/networks/base_s_adm__none_2050.nc"

NETWORK_FILE_SUFFIX = ".nc"
MODEL_YEARS = [2020, 2030, 2040, 2050]
COUNTRY = "AT"
BUS_CARRIERS = ["solid biomass", "solid biomass for industry"]
GROUPBY = ["carrier", "country"]
COMPONENTS_SUM = ["Link", "Load"]
GROUPBY_TIME_TIMESERIES = False
GROUPBY_TIME_SUM = "sum"

EXCLUDED_CARRIER = "solid biomass transport"
ABSOLUTE_VALUES = True

PLOT_RENDERER = "browser"
TIMESERIES_TITLE = "Energy Balance in Austria | single year"
TIMESERIES_YAXIS_TITLE = "MWh_LHV"
PIE_SINGLE_TITLE = "Biomass usage | 2050"
PIE_COLLECTION_TITLE = "Biomass usage by modelling year (AT)"


def list_network_files(folder):
    """Return sorted .nc files from a folder as full paths."""
    files = [
        os.path.join(folder, file_name)
        for file_name in os.listdir(folder)
        if file_name.endswith(NETWORK_FILE_SUFFIX) and os.path.isfile(os.path.join(folder, file_name))
    ]
    return sorted(files)


def get_energy_balance(network, groupby_time, components=None):
    """Get AT energy balance with a consistent filter setup."""
    kwargs = {
        "bus_carrier": BUS_CARRIERS,
        "groupby": GROUPBY,
        "groupby_time": groupby_time,
    }
    if components is not None:
        kwargs["components"] = components

    return network.statistics.energy_balance(**kwargs).xs(COUNTRY, level="country")


def prepare_carrier_usage_dataframe(stats_series):
    """Convert raw stats output to a plot-ready table."""
    df = pd.DataFrame(stats_series, columns=["value"]).reset_index()
    df = df[df["carrier"] != EXCLUDED_CARRIER].copy()
    if ABSOLUTE_VALUES:
        df["value"] = df["value"].abs()
    return df


def plot_stacked_timeseries(df_raw):
    """Plot positive and negative stacked area traces for one network year."""
    plot_df = df_raw.copy()
    x_parsed = pd.to_datetime(plot_df.columns, errors="coerce")
    x_values = x_parsed if x_parsed.notna().all() else plot_df.columns.astype(str)

    fig = go.Figure()
    palette = px.colors.qualitative.Plotly

    for i, (series_name, row) in enumerate(plot_df.iterrows()):
        label = " | ".join(map(str, series_name)) if isinstance(series_name, tuple) else str(series_name)
        color = palette[i % len(palette)]
        y = pd.to_numeric(row, errors="coerce").fillna(0.0).values

        y_pos = [v if v > 0 else 0 for v in y]
        y_neg = [v if v < 0 else 0 for v in y]

        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=y_pos,
                mode="lines",
                stackgroup="positive",
                legendgroup=label,
                name=label,
                line=dict(width=0.8, color=color),
                hovertemplate="<b>%{fullData.name}</b><br>time=%{x}<br>value=%{y:.3f}<extra></extra>",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=y_neg,
                mode="lines",
                stackgroup="negative",
                legendgroup=label,
                name=label + " (negative)",
                showlegend=False,
                line=dict(width=0.8, color=color),
                hovertemplate="<b>%{fullData.legendgroup}</b><br>time=%{x}<br>value=%{y:.3f}<extra></extra>",
            )
        )

    fig.add_hline(y=0, line_width=1, line_color="black")
    fig.update_layout(
        title=TIMESERIES_TITLE,
        xaxis_title="Time",
        yaxis_title=TIMESERIES_YAXIS_TITLE,
        hovermode="x unified",
        template="plotly_white",
    )
    fig.show(renderer=PLOT_RENDERER)


def plot_pie(df, title):
    """Plot a single pie chart from prepared data."""
    fig = px.pie(df, values="value", names="carrier", title=title)
    fig.show(renderer=PLOT_RENDERER)


def collect_collection_usage(network_collection, years):
    """Return raw stats per year and one concatenated dataframe for all years."""
    stats_by_year = {}
    rows = []

    for year, net in zip(years, network_collection):
        stats = get_energy_balance(
            network=net,
            groupby_time=GROUPBY_TIME_SUM,
            components=COMPONENTS_SUM,
        )
        stats_by_year[year] = stats

        df_year = prepare_carrier_usage_dataframe(stats)
        df_year["year"] = year
        rows.append(df_year)

    if not rows:
        raise ValueError("No networks were processed. Check NETWORKS_FOLDER and NETWORK_FILE_SUFFIX.")

    df_nc = pd.concat(rows, ignore_index=True)
    if df_nc.empty:
        raise ValueError("statistics.energy_balance returned no rows for the NetworkCollection.")

    return stats_by_year, df_nc


def plot_collection_pies(stats_by_year, years):
    """Plot one pie chart per year as subplot domains."""
    fig = make_subplots(
        rows=1,
        cols=len(years),
        specs=[[{"type": "domain"} for _ in years]],
        subplot_titles=[str(year) for year in years],
    )

    for col, year in enumerate(years, start=1):
        df_year = prepare_carrier_usage_dataframe(stats_by_year[year])
        fig_pie = px.pie(df_year, values="value", names="carrier", title="Biomass usage")
        fig.add_trace(fig_pie.data[0], row=1, col=col)

    fig.update_layout(
        title=PIE_COLLECTION_TITLE,
        showlegend=True,
    )
    fig.show(renderer=PLOT_RENDERER)


def main():
    network_files = list_network_files(NETWORKS_FOLDER)
    nc = pypsa.NetworkCollection(network_files)

    # Plot time series and single-year pie for one selected network file.
    single_network = pypsa.Network(SINGLE_NETWORK_FILE)
    df_raw_timeseries = get_energy_balance(
        network=single_network,
        groupby_time=GROUPBY_TIME_TIMESERIES,
    )
    plot_stacked_timeseries(df_raw_timeseries)

    df_raw_sum = get_energy_balance(
        network=single_network,
        groupby_time=GROUPBY_TIME_SUM,
        components=COMPONENTS_SUM,
    )
    df_single_pie = prepare_carrier_usage_dataframe(df_raw_sum)
    plot_pie(df_single_pie, PIE_SINGLE_TITLE)

    # Plot collection-wide pies for all model years.
    stats_by_year, _df_nc = collect_collection_usage(nc, MODEL_YEARS)
    plot_collection_pies(stats_by_year, MODEL_YEARS)


if __name__ == "__main__":
    main()