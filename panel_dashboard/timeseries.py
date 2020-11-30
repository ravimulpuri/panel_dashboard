import logging
import math
import json
import os
import argparse
from pathlib import Path
from ast import literal_eval

import pandas as pd
import numpy as np
import panel as pn
import panel.widgets as pnw
import param as pm
import holoviews as hv
import hvplot.pandas


from sklearn.preprocessing import StandardScaler
from panel_dashboard.accessors import register_dataframe_accessor, register_dataframe_method
from collections import Counter


class UnableToReadFilename(Exception):
    """Raise exception when pandas is not able to read file"""

    pass


# log scaling for the data
def log_scaling(s):
    """
    log scale the data

    Parameters
    ----------
    s : pd.Series
        pandas dataframe

    Returns
    -------
    pd.Series
        log-scaled data
    """
    index_ = s.index
    tag = s.name

    yvals = s.values
    l, m, h = np.nanpercentile(yvals, [25, 50, 75])
    iqr = h - l

    if np.isclose(iqr, 0):
        iqr = 1
    s = (yvals - m) / (3 * iqr)
    s = np.arcsinh(s) * 3 * iqr
    return pd.Series(s, index=index_, name=tag)


# read hdf5 format
def read_data(filename, filetype, read_kwargs):
    """
    Create pandas dataframe

    Parameters
    ----------
    filename : Union[str, Path]
        location of the file
    filetype : str
        extension for file. Examples include csv, parquet etc.
    read_kwargs : dict
        additional arguments required to read the data

    Returns
    -------
    pd.DataFrame
        Pandas dataframe created from the arguments

    Raises
    ------
    UnableToReadFilename
        Raise thie error if the function is unable to read the filename because of
        its filetype or read_kwargs
    """
    filetype = filetype.lower()
    try:
        if filetype == "csv":
            df = pd.read_csv(filename, **read_kwargs)
        elif filetype == "excel":
            df = pd.read_excel(filename, **read_kwargs)
        elif filetype == "feather":
            df = pd.read_feather(filename, **read_kwargs)
        elif filetype == "hdf":
            df = pd.read_hdf(filename, **read_kwargs)
        elif filetype == "parquet":
            df = pd.read_parquet(filename, **read_kwargs)
        elif filetype == "pickle":
            df = pd.read_pickle(filename, **read_kwargs)
        else:
            raise UnableToReadFilename(
                f"Filetype {filetype} is not supported at this time. Supported filetypes are "
                f"csv, excel, feather, hdf, parquet, pickle"
            )
        return df.select_dtypes(exclude=["object"]).sort_index()
    except:  # TODO: Any other to cover all the cases without using except?
        raise UnableToReadFilename(f"Unable to read {filename} with the provided read_kwargs {read_kwargs}")


def santize_feature_aliases(feature_aliases, columns):
    """
    Adjust feature aliases to avoid duplicates

    Parameters
    ----------
    feature_aliases : dict
        dictionary of tags as keys as descriptions as values
    columns : Iterable
        Iterable of tags

    Returns
    -------
    dict
        feature aliases after removing duplicates and avoiding collison
    """

    if feature_aliases is None:
        feature_aliases = {c: c for c in columns}

    # check for additional entries in feature_aliases that are not in columns and remove them
    additional_entries = [c for c in feature_aliases if c not in columns]
    for entry in additional_entries:
        feature_aliases.pop(entry, None)

    # check if the descriptions are string and not NaN's / numeric type
    for c in feature_aliases:

        # if key is int. Keys are descriptions should be in
        # str format to avoid issues in duplicate values check
        if isinstance(c, int):
            feature_aliases[str(c)] = feature_aliases.pop(c)

        # if description is int
        if isinstance(feature_aliases[c], int):
            feature_aliases[c] = str(feature_aliases[c])

        # if tag is empty string
        if c == "" and (not pd.isnull(feature_aliases[c]) or feature_aliases[c] != ""):
            feature_aliases[feature_aliases[c]] = feature_aliases.pop(c)  # tag mapped to description
        elif c == "":
            _ = feature_aliases.pop(c, None)

        # if description is nan or empty string but tag is valid
        if c != "" and (pd.isnull(feature_aliases[c]) or feature_aliases[c] == ""):
            feature_aliases[c] = c  # description mapped to tag

    # check if descriptions are unique
    cnt = Counter(list(feature_aliases.values()))
    duplicate_descriptions = set([d for d in cnt if cnt[d] > 1])

    for k in columns:
        # check if description is avaialble
        if k not in feature_aliases:
            feature_aliases[k] = f"No description available for {k}"

        # if descriptions are available, add tag to the description if it is not unique
        else:
            if feature_aliases[k] in duplicate_descriptions:
                feature_aliases[k] += f" {k}"

    # sort the features
    sorted_features = sorted(list(feature_aliases.keys()))
    sorted_feature_aliases = {k: feature_aliases[k] for k in sorted_features}
    return sorted_feature_aliases


def get_bounds(df):
    """
    Get bounds for each tag in the dataframe

    Parameters
    ----------
    df : pd.DataFrame
        Data to compute bounds for

    Returns
    -------
    Dict
        Dictionary of tags as keys as tuple of min and max
        as values
    """
    tag_max = df.max().to_dict()  # cache max and min values
    tag_min = df.min().to_dict()
    tag_bounds = {}

    for tag in tag_max:
        if pd.isna(tag_min[tag]) and pd.isna(tag_max[tag]):
            tag_bounds[tag] = (-1, 1)  # dummy placeholder
        elif math.isclose(tag_max[tag], tag_min[tag], rel_tol=1e-09):
            tag_bounds[tag] = (tag_min[tag] - 0.5, tag_max[tag] + 0.5)
        else:
            tag_bounds[tag] = (tag_min[tag], tag_max[tag])
    return tag_bounds


def deploy_at_port(panel_obj, port_, websocket_origin=None):
    """
    get port and deploy the panel

    Parameters
    ----------
    panel_obj :
        Panel object
    port_ : int
        Port to launch the dashboard on
    websocket_origin : int, optional
        Websocket origin to allow (useful for running remotely), by default None

    Returns
    -------
    Panel dashboard
    """
    panel_db = None
    while True:
        try:
            print(f"Starting server on port {port_}")
            if websocket_origin:
                panel_db = panel_obj.show(port_, websocket_origin)
            else:
                panel_db = panel_obj.show(port_)
            break
        except OSError:
            print(f"Port {port_} in use! Trying next one {port_ + 1}")
            port_ += 1
            continue
    return panel_db


class BasePanel:
    """
    Base Panel for all the dashboards.

    This class creates following attributes
    1) cleans dataframe from categorical features
    2) creates/cleans feature_aliases, rev_feature_aliases
    3) creates tag_bounds

    This class following useful methods
    1) dashboard method which creates tabs based on the plot_view and summary methods
    2) host method which can host the output of dashboard method for a given port and
    websocket_origin

    Parameters
    ----------
    df : pd.DataFrame
        Pandas DataFrame

    feature_aliases: dict
        dictionary with keys as column names and values as column name aliases.
        This is useful for showing the tag description in the dashboard, if needed. feature_aliases will be
        loaded from tag_summary_filename if it is availabe in the file

    port : int
        Port to launch the server

    websocket_origin : Optional[str]
        Websocket origin to allow (useful for running remotely)

    sample_ratio: float
        Fraction of data that should be used for visualizations. Default is 1.0,
        which implies entire data will be used to generate data
    """

    def __init__(
        self,
        df,
        *,
        feature_aliases=None,
        port=5006,
        websocket_origin=None,
        sample_rate=1.0,
    ):
        self.df = df.select_dtypes(exclude=["object"]).sort_index()
        self.columns = sorted(list(self.df.columns))
        self.port = port
        self.websocket_origin = websocket_origin
        self.db = None

        self.df = self.df.sample(frac=sample_rate).sort_index()

        # clean/create feature aliases
        self.feature_aliases = feature_aliases
        self.rev_feature_aliases = dict(zip(self.feature_aliases.values(), self.feature_aliases.keys()))

        # compute bounds of each tag
        self.tag_bounds = get_bounds(self.df)

    def dashboard(self):
        pass

    def host(self):
        self.db = deploy_at_port(self.dashboard(), self.port, self.websocket_origin)
        return self.db

    def stop(self):
        if self.db is None:
            return (
                "Dashboard is not hosted for it to be stopped. Use self.host()"
                " method to host the dashboard and later use self.stop() to stop "
                " the dashboard and free up the port"
            )
        self.db.stop()
        pass


class TagPlot(BasePanel, pm.Parameterized):
    """
    Create dashboard which plots to selected tag, its histogram and brief description pane

    Parameters
    ----------
    df : pd.DataFrame
        Pandas DataFrame

    feature_aliases: dict
        dictionary with keys as column names and values as column name aliases.
        This is useful for showing the tag description in the dashboard, if needed

    describe: bool
        Should the dashboard include pandas.tag_series.describe() along with the plot

    x_label : str
        x_axis label for the plots

    port : int
        Port to launch the server

    websocket_origin : str
        Websocket origin to allow (useful for running remotely)

    params : dict
        Additional parameters for the param.Parametrized class
    """

    def __init__(
        self,
        df,
        *,
        feature_aliases=None,
        describe=True,
        x_label="timestamp",
        port=5006,
        websocket_origin=49179,
        sample_rate=1.0,
        plot_width=600,
        plot_height=400,
        **params,
    ):

        BasePanel.__init__(
            self,
            df,
            feature_aliases=feature_aliases,
            port=port,
            websocket_origin=websocket_origin,
            sample_rate=sample_rate,
        )
        self.plot_width = plot_width
        self.plot_height = plot_height
        self.describe = describe
        self.x_label = x_label

        tags = sorted(list(df.columns))
        tag = tags[0]
        bounds = self.tag_bounds[tag]

        # widget objects
        self.feature = pnw.Select(value=tag, options=tags, name="Ticker")
        self.description = pnw.Select(
            value=self.feature_aliases[tag],
            options=sorted(list(self.feature_aliases.values())),
            name="Company",
        )
        self.tag_range = pnw.RangeSlider(start=bounds[0], end=bounds[1], value=bounds, name="Feature Range")
        self.log_scale = pnw.Checkbox(
            name="Log scale",
            value=False,
        )

        pm.Parameterized.__init__(self, **params)

    @pn.depends("feature.value", watch=True)
    def feature_update(self):

        # update description
        if self.description.value != self.feature_aliases[self.feature.value]:
            self.description.value = str(self.feature_aliases[self.feature.value])

    @pn.depends("description.value", watch=True)
    def description_update(self):
        # update feature and tag data
        if self.feature.value != self.rev_feature_aliases[self.description.value]:
            self.feature.value = self.rev_feature_aliases[self.description.value]

    @pn.depends("feature.value", "log_scale.value")
    def plot_view(self):

        data = self.df[self.feature.value]
        data = data.loc[data.first_valid_index() :]

        if self.log_scale.value:
            data = pd.Series(np.log(data.values), index=data.index)
            data.name = f"{self.feature.value}  - log of closing price"
        else:
            data.name = f"{self.feature.value}  - closing price"

        df_ma_15 = data.rolling(window=15).mean()
        df_ma_30 = data.rolling(window=30).mean()

        df_ma_15.name = "moving average - 15 days"
        df_ma_30.name = "moving average - 30 days"

        tag_plot = data.hvplot.line(
            title=self.feature.value, xlabel="Timestamp", height=self.plot_height, width=self.plot_width
        )

        ma_15 = df_ma_15.hvplot.line(
            title=self.feature.value, xlabel="Timestamp", height=self.plot_height, width=self.plot_width
        )
        ma_30 = df_ma_30.hvplot.line(
            title=self.feature.value, xlabel="Timestamp", height=self.plot_height, width=self.plot_width
        )

        min_ = self.tag_bounds[self.feature.value][0]
        max_ = self.tag_bounds[self.feature.value][1]

        if self.log_scale.value:
            min_, max_ = data.min(), data.max()

        histogram = data.hvplot.hist(
            bins=100, bin_range=(min_, max_), muted_alpha=0, legend="top", height=400, width=200, title="Histogram"
        )
        right_col = [histogram]

        frame = data.describe().reset_index()
        description_table = hv.Table(frame).opts(height=250, width=400)

        second_plot = hv.Layout(histogram + description_table).cols(2)

        plots = hv.Layout(((tag_plot * ma_15 * ma_30) << histogram) + description_table).cols(1)

        return plots

    def dashboard(self):
        return pn.Column(
            pn.Row(
                pn.Column(self.feature, self.description, self.log_scale),
                self.plot_view,
            )
        )


def dashboard():
    # Parse arguments
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Create dashboard with a pandas readable file (csv, hdf, parquet etc.)",
    )
    parser.add_argument(
        "-f",
        "--filename",
        help="Location of file. By default, it accepts csv file that should be readable as "
        "pd.read_parquet(filename). To accept different type of file use the "
        "filetype and read_kwargs arguments, (type: %(type)s)",
        type=str,
        default="/mnt/data/final/historical_stock_prices.parquet",
    )
    parser.add_argument(
        "-ft",
        "--filetype",
        help="Type of file that is provided at filename argument. Available options can be "
        "csv, excel, feather, hdf, parquet, pickle etc., (type: %(type)s)",
        type=str,
        default="parquet",
        choices=["csv", "excel", "feather", "hdf", "parquet", "pickle"],
    )
    parser.add_argument(
        "-kwgs",
        "--read-kwargs",
        help="Additional keyword arguments to read the {filename} using the pandas read_{filetype}. "
        "Keywords should be provided in the following format -kwgs foo1=bar foo2=10"
        "(type: %(type)s)",
        type=str,
        default=None,
        nargs="*",
    )
    parser.add_argument(
        "-fa",
        "--feature-aliases",
        help="Path to the json file which contains dictionary object with keys as column names and "
        "values as column name aliases, (type: %(type)s)",
        type=str,
        default="/mnt/data/final/feature_aliases.json",
    )
    parser.add_argument(
        "-d",
        "--describe",
        help="Should the dashboard include pandas.tag_series.describe() along with the plot, " "(type: %(type)s)",
        type=bool,
        default=True,
    )
    parser.add_argument(
        "-p",
        "--port",
        help="Port to launch the dashboard on, (type: %(type)s)",
        type=int,
        default=5006,
    )
    parser.add_argument(
        "-s",
        "--sample_rate",
        help="Fraction of data that should be used for plots.  A %(type)s between (0.0, 1.0] that defaults to 1.0",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "-w",
        "--websocket-origin",
        help="Websocket origin to allow (useful for running remotely), (type: %(type)s)",
        type=int,
        default=49179,
    )
    args = parser.parse_args()

    # check if options are provided
    if args.filename is None:
        raise FileNotFoundError("Either filename or arrow-folder should be provided to create a dashboard")

    if args.feature_aliases:
        feature_aliases = json.load(open(args.feature_aliases, "r"))
    else:
        feature_aliases = None

    # develop dictionary from args.read_kwargs
    read_kwargs = {}
    if args.read_kwargs:
        for ar in args.read_kwargs:
            k_v = ar.split("=")
            try:
                read_kwargs[k_v[0]] = literal_eval(k_v[1])
            except ValueError:
                read_kwargs[k_v[0]] = k_v[1]

    df = read_data(args.filename, args.filetype, read_kwargs)
    feature_aliases = santize_feature_aliases(feature_aliases, list(df.columns))
    plot = TagPlot(
        df,
        feature_aliases=feature_aliases,
        describe=args.describe,
        x_label="timestamp",
        port=args.port,
        websocket_origin=args.websocket_origin,
        sample_rate=args.sample_rate,
    )

    plot.host()


if __name__ == "__main__":
    dashboard()
