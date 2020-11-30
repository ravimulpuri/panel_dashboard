import pandas as pd
import subprocess
from tqdm import tqdm


def download_data():
    kaggle_dataset = "ehallmar/daily-historical-stock-prices-1970-2018"
    out1 = subprocess.Popen(
        ["kaggle", "datasets", "download", "-d", kaggle_dataset], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )

    out2 = subprocess.Popen(["unzip", f"{kaggle_dataset.split('/')[-1].zip}"])

    pass


def convert_data():
    df = pd.read_csv("data/raw/historical_stock_prices.csv")
    g1 = df.groupby(["ticker", "date"])["close"].min()

    df_new = pd.DataFrame(index=g1.index.levels[1], columns=g1.index.levels[0])
    for c in tqdm(df_new.columns):
        df_new.loc[g1[c].index, c] = g1[c]

    df_new.to_parquet("data/final/historical_stock_prices.parquet")

    pass
