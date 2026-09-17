import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pypsa
    import pandas as pd 
    pd.options.plotting.backend = "plotly"
    import os

    return mo, os, pd, pypsa


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Check road transport demand and technology share update
    > update with netzero 2040 - Scenarios (see ESM_preprocessing)

    **macht noch nicht, was es soll!**
    """)
    return


@app.cell
def _():
    n_dict = {
        "2025": "base_s_adm__none_2025.nc",
        "2030": "base_s_adm__none_2030.nc",
       # "2040": "base_s_adm__none_2040.nc",
        "2050": "base_s_adm__none_2050.nc",
    }
    return (n_dict,)


@app.cell
def _(n_dict, os, pypsa):
    high_demand_dict = {k: os.path.join("results/future-road-transport-demand/with_netzero_high_transport_demand/networks", v) for k,v in n_dict.items()}
    nc_high_demand = pypsa.NetworkCollection(high_demand_dict)

    low_demand_dict = {k: os.path.join("results/future-road-transport-demand/with_netzero_low_transport_demand/networks", v) for k,v in n_dict.items()}
    nc_low_demand = pypsa.NetworkCollection(low_demand_dict)

    basic_demand_dict = {k: os.path.join("results/future-road-transport-demand/without_netzero_demand/networks", v) for k, v in n_dict.items()}
    nc_basic_demand = pypsa.NetworkCollection(basic_demand_dict)
    return nc_basic_demand, nc_high_demand, nc_low_demand


@app.cell
def _(nc_low_demand):
    nc_low_demand.statistics.energy_balance(
                        components = "Load",
                        direction="withdrawal",
                        carrier = ['land transport oil'],
                        groupby = "country"
                        ).xs("AT", level = "country")

    return


@app.cell
def _(nc_basic_demand, nc_high_demand, nc_low_demand):
    nc_dict = {
        "low_demand": nc_low_demand,
        "high_demand" : nc_high_demand,
        "basic_demand": nc_basic_demand
    }

    demand_dict = {}
    for k, nc in nc_dict.items():
        demand_dict.update({
                k: nc.statistics.energy_balance(
                        components = "Load",
                        direction="withdrawal",
                        carrier = ['land transport EV', 'land transport fuel cell', 'land transport oil'],
                        groupby = "country"
                        ).xs("AT", level = "country")
                    })
    return (demand_dict,)


@app.cell
def _(demand_dict, pd):
    df_demand = pd.DataFrame.from_dict(demand_dict)
    return (df_demand,)


@app.cell
def _(df_demand):
    df_demand.plot(title = "Transport Demand NetZero2040 (low_demand, high_demand) compared to pypsa-eur demand (basic_demand)")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    """)
    return


@app.cell
def _(nc_low_demand):
    low_demand = nc_low_demand.statistics.energy_balance(
        components = "Load",
        direction="withdrawal",
        carrier = ['land transport EV', 'land transport fuel cell', 'land transport oil'],
        groupby = ["country", "carrier"]
        ).xs("AT", level = "country")
    return (low_demand,)


@app.cell
def _(low_demand, nc_basic_demand, nc_high_demand, pd):
    df = pd.DataFrame(index = low_demand.index)
    df["low demand"] = low_demand
    df["high demand"] = nc_high_demand.statistics.energy_balance(
        components = "Load",
        direction="withdrawal",
        carrier = ['land transport EV', 'land transport fuel cell', 'land transport oil'],
        groupby = ["country", "carrier"]
        ).xs("AT", level = "country")
    df["basic demand"] = nc_basic_demand.statistics.energy_balance(
        components = "Load",
        direction="withdrawal",
        carrier = ['land transport EV', 'land transport fuel cell', 'land transport oil'],
        groupby = ["country", "carrier"]
        ).xs("AT", level = "country")
    return (df,)


@app.cell
def _(df):
    df
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
