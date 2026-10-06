# Tests for the weather data pipeline

from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

# Local imports
from src.pipeline import (
    aggregate_daily_weather,
    fetch_weather,
    fetch_weather_all_cities,
    hourly_forecasts_to_dataframe,
    merge_city_metadata,
    normalize_city_name,
    normalize_country_name,
    parse_cities_csv,
)


# Test normalize_city_name
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  pArIS!!  ", "Paris"),
        ("tOkYo!!", "Tokyo"),
        ("mumbai (bombay)", "Mumbai"),
        ("seoul#1", "Seoul"),
        ("  new york  ", "New York"),
        ("São   Paulo", "São Paulo"),
    ],
    ids=["Paris", "Tokyo", "Mumbai", "Seoul", "New York", "Sao Paulo"],
)
def test_normalize_city_name(raw, expected):
    assert normalize_city_name(raw) == expected


# Test normalize_country_name
def test_normalize_country_name():
    assert normalize_country_name("  u.s.a. ") == "USA"
    assert normalize_country_name("SOUTH  KOREA") == "South Korea"


# Test parse_cities_csv_normalizes_dirty_rows
def test_parse_cities_csv_normalizes_dirty_rows(tmp_path):
    csv_path = tmp_path / "cities.csv"
    csv_path.write_text(
        " City_Name , country ,Latitude, LONGITUDE\n"
        "  pArIS!!  ,FRANCE,48.85,2.35\n"
        "TOkyO,japan,35.68,139.69\n",
        encoding="utf-8",
    )

    data_frame = parse_cities_csv(csv_path)

    assert list(data_frame["city"]) == ["Paris", "Tokyo"]
    assert list(data_frame["country"]) == ["France", "Japan"]
    assert len(data_frame) == 2


# Test hourly_forecasts_to_dataframe_drops_missing_and_parses_time
def test_hourly_forecasts_to_dataframe_drops_missing_and_parses_time():
    raw_results = [
        {
            "city": "Paris",
            "data": {
                "time": ["2026-01-01T00:00", "not-a-date", "2026-01-01T02:00"],
                "temperature_2m": [15.0, 16.0, None],
                "precipitation": [1.0, 0.5, 0.0],
            },
        },
        {"city": "Tokyo", "data": None},
    ]

    data_frame = hourly_forecasts_to_dataframe(raw_results)

    assert len(data_frame) == 1
    assert data_frame.iloc[0]["City"] == "Paris"
    assert data_frame.iloc[0]["Temp_C"] == 15.0
    assert pd.api.types.is_datetime64_any_dtype(data_frame["Time"])


# Test aggregate_daily_weather_max_temp_and_precip_sum
def test_aggregate_daily_weather_max_temp_and_precip_sum():
    hourly_df = pd.DataFrame(
        {
            "City": ["Paris", "Paris", "Tokyo"],
            "Time": pd.to_datetime(
                ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T00:00"]
            ),
            "Temp_C": [15.0, 30.0, 10.0],
            "Precip_mm": [1.0, 2.0, 0.5],
        }
    )

    summary = aggregate_daily_weather(hourly_df)
    paris = summary[summary["City"] == "Paris"].iloc[0]

    assert paris["Max_Temp_C"] == 30.0
    assert paris["Total_Precip_mm"] == 3.0
    assert len(summary) == 2


# Test merge_city_metadata_joins_normalized_names
def test_merge_city_metadata_joins_normalized_names():
    daily_summary = pd.DataFrame(
        {
            "City": ["Paris"],
            "Date": [pd.Timestamp("2026-01-01").date()],
            "Max_Temp_C": [30.0],
            "Total_Precip_mm": [3.0],
        }
    )
    cities = pd.DataFrame(
        {
            "city": ["Paris"],
            "country": ["France"],
            "latitude": [48.85],
            "longitude": [2.35],
        }
    )

    merged = merge_city_metadata(daily_summary, cities)

    assert merged.iloc[0]["country"] == "France"
    assert merged.iloc[0]["latitude"] == 48.85


# Test _hourly_payload returns a valid hourly payload
def _hourly_payload():
    return {
        "hourly": {
            "time": ["2026-01-01T00:00"],
            "temperature_2m": [22.5],
            "precipitation": [0.0],
        }
    }


# Test fetch_weather uses mocked API response
def test_fetch_weather_uses_mocked_api_response():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = _hourly_payload()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_response

    result = fetch_weather(mock_client, "Paris", 48.85, 2.35)

    assert result["city"] == "Paris"
    assert result["data"]["temperature_2m"][0] == 22.5
    mock_client.get.assert_called_once()
    mock_response.raise_for_status.assert_called_once()


# Test fetch_weather returns None on HTTP error
def test_fetch_weather_returns_none_on_http_error():
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.ConnectError("offline")

    result = fetch_weather(mock_client, "Paris", 48.85, 2.35)

    assert result == {"city": "Paris", "data": None}


# Test fetch_weather_all_cities does not hit network
@patch("src.pipeline.httpx.Client")
def test_fetch_weather_all_cities_does_not_hit_network(mock_client_cls):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = _hourly_payload()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    mock_client_cls.return_value.__enter__.return_value = mock_client

    cities = pd.DataFrame(
        {
            "city": ["Paris", "Tokyo"],
            "latitude": [48.85, 35.68],
            "longitude": [2.35, 139.69],
        }
    )
    results = fetch_weather_all_cities(cities)

    assert len(results) == 2
    assert mock_client.get.call_count == 2
    assert all(row["data"] is not None for row in results)
