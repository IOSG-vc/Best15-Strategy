"""Minimal local fredapi-compatible shim for the handoff runner.

The copied V3 production script imports ``from fredapi import Fred``. Some
handoff environments do not have the third-party ``fredapi`` package installed,
so this file provides the small subset we need using FRED's HTTP API.
"""

from __future__ import annotations

import pandas as pd
import requests


class Fred:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def get_series(self, series_id: str, observation_start: str | None = None):
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        if observation_start:
            params["observation_start"] = observation_start

        response = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        values = {}
        for row in response.json().get("observations", []):
            value = row.get("value")
            if value in (None, "."):
                continue
            values[pd.Timestamp(row["date"])] = float(value)

        return pd.Series(values, dtype="float64").sort_index()
