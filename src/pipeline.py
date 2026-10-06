"""Weather data pipeline: parse and normalize dirty city CSV input."""

from __future__ import annotations

# Standard library imports
import logging
import os
import re
import time
from pathlib import Path

# Third-party imports
import httpx
import pandas as pd
from dotenv import load_dotenv

# Project paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = ROOT_DIR / "reports"
RAW_CITIES_CSV = DATA_DIR / "raw_cities.csv"
EXCEL_REPORT_PATH = REPORTS_DIR / "weather_summary.xlsx"
JSON_ALERTS_PATH = REPORTS_DIR / "alerts.json"
HEAT_ALERT_THRESHOLD_C = 30.0

# Load environment variables from .env file
load_dotenv(ROOT_DIR / ".env")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Configure logging
logging.basicConfig(
    filename=ROOT_DIR / "pipeline.log",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.info("Pipeline configuration successfully loaded.")

# Define column aliases for messy CSV headers
COLUMN_ALIASES = {
    "city": "city",
    "city_name": "city",
    "cityname": "city",
    "country": "country",
    "lat": "latitude",
    "latitude": "latitude",
    "lon": "longitude",
    "lng": "longitude",
    "long": "longitude",
    "longitude": "longitude",
}

# Normalize messy CSV headers to snake_case aliases
def normalize_header(name: object) -> str:
    cleaned = str(name).strip().lower()
    cleaned = re.sub(r"[\s\-]+", "_", cleaned)
    cleaned = re.sub(r"[^a-z0-9_]", "", cleaned)
    return COLUMN_ALIASES.get(cleaned, cleaned) # type: ignore


# Clean a city label with regex search/replace, strip, and title-case
def normalize_city_name(value: object) -> str:
    text = str(value).strip()

    # Drop parenthetical aliases: "mumbai (bombay)" -> "mumbai"
    text = re.sub(r"\([^)]*\)", " ", text)

    # Keep the primary name when alternates are joined by slash or comma.
    split_match = re.search(r"^(.+?)(?:\s*[/,].*)?$", text)
    if split_match:
        text = split_match.group(1)

    # Remove remaining special characters; keep letters, spaces, and hyphens.
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\d_]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().title()


# Clean a country label with the same string-normalization toolkit
def normalize_country_name(value: object) -> str:
    text = str(value).strip()
    text = re.sub(r"\.", "", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\d_]+", "", text)
    text = re.sub(r"\s+", " ", text)
    cleaned = text.strip().title()
    if cleaned.upper() == "USA":
        return "USA"
    return cleaned


# Parse the raw cities CSV and return normalized city coordinates
def parse_cities_csv(filepath: str | Path | None = None) -> pd.DataFrame:
    path = Path(filepath) if filepath is not None else RAW_CITIES_CSV
    logger.info("Loading raw city data from %s", path)

    try:
        data_frame = pd.read_csv(path)
    except OSError:
        logger.error("Failed to read city CSV at %s", path)
        raise

    data_frame.columns = [normalize_header(column) for column in data_frame.columns]

    required = ("city", "latitude", "longitude")
    missing = [column for column in required if column not in data_frame.columns]
    if missing:
        logger.error(
            "CSV is missing required columns %s. Found: %s",
            missing,
            list(data_frame.columns),
        )
        raise ValueError(
            f"CSV is missing required columns {missing}. Found: {list(data_frame.columns)}"
        )

    data_frame["city"] = data_frame["city"].map(normalize_city_name)
    if "country" in data_frame.columns:
        data_frame["country"] = data_frame["country"].map(normalize_country_name)

    data_frame["latitude"] = pd.to_numeric(data_frame["latitude"], errors="coerce")
    data_frame["longitude"] = pd.to_numeric(data_frame["longitude"], errors="coerce")

    data_frame = data_frame.dropna(subset=["city", "latitude", "longitude"])
    data_frame = data_frame[data_frame["city"].str.len() > 0]
    data_frame = data_frame.reset_index(drop=True)
    logger.info("Cleaned %s city records.", len(data_frame))
    return data_frame


# Fetch hourly forecast data for a single city from Open-Meteo
def fetch_weather(client: httpx.Client, city: str, lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation",
        "timezone": "auto",
        "temperature_unit": os.getenv("WEATHER_UNIT", "celsius"),
    }
    try:
        response = client.get(FORECAST_URL, params=params, timeout=10.0)
        response.raise_for_status()
        hourly = response.json().get("hourly")
        logger.info("Successfully fetched weather data for %s", city)
        return {"city": city, "data": hourly}
    except httpx.HTTPError:
        logger.error("Failed to fetch weather data for %s", city)
        return {"city": city, "data": None}


# Fetch weather data sequentially, one city at a time
def fetch_weather_all_cities(cities: pd.DataFrame) -> list[dict]:
    results = []
    with httpx.Client() as client:
        for _, row in cities.iterrows():
            results.append(
                fetch_weather(client, row["city"], row["latitude"], row["longitude"])
            )
    return results


# Parse Open-Meteo hourly JSON into a DataFrame with datetime timestamps
def hourly_forecasts_to_dataframe(raw_results: list[dict]) -> pd.DataFrame:
    records = []

    for result in raw_results:
        city = result["city"]
        hourly = result["data"]
        if not hourly:
            logger.error("No hourly forecast data for %s", city)
            continue

        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        precips = hourly.get("precipitation", [])

        for timestamp, temp, precip in zip(times, temps, precips):
            records.append(
                {
                    "City": city,
                    "Time": timestamp,
                    "Temp_C": temp,
                    "Precip_mm": precip,
                }
            )

    if not records:
        logger.error("No valid records found to transform.")
        return pd.DataFrame(columns=["City", "Time", "Temp_C", "Precip_mm"])

    data_frame = pd.DataFrame(records)
    data_frame["Time"] = pd.to_datetime(data_frame["Time"], errors="coerce")
    data_frame["Temp_C"] = pd.to_numeric(data_frame["Temp_C"], errors="coerce")
    data_frame["Precip_mm"] = pd.to_numeric(data_frame["Precip_mm"], errors="coerce")

    row_count = len(data_frame)
    data_frame = data_frame.dropna(subset=["Time", "Temp_C", "Precip_mm"])
    dropped = row_count - len(data_frame)
    if dropped:
        logger.warning("Dropped %s hourly rows with missing values.", dropped)

    logger.info("Loaded %s hourly forecast rows into a DataFrame.", len(data_frame))
    return data_frame


# Aggregate hourly weather data into daily summaries by city
def aggregate_daily_weather(hourly_df: pd.DataFrame) -> pd.DataFrame:
    if hourly_df.empty:
        logger.error("No hourly records available to aggregate.")
        return pd.DataFrame(columns=["City", "Date", "Max_Temp_C", "Total_Precip_mm"])

    data_frame = hourly_df.copy()
    data_frame["Date"] = data_frame["Time"].dt.date
    daily_summary = (
        data_frame.groupby(["City", "Date"], as_index=False)
        .agg(Max_Temp_C=("Temp_C", "max"), Total_Precip_mm=("Precip_mm", "sum"))
    )
    logger.info("Aggregated daily weather for %s city-day rows.", len(daily_summary))
    return daily_summary


# Join aggregated weather stats with normalized city names from the CSV
def merge_city_metadata(
    daily_summary: pd.DataFrame, cities: pd.DataFrame
) -> pd.DataFrame:
    city_lookup = cities.rename(columns={"city": "City"}).drop_duplicates(subset=["City"])
    merged = daily_summary.merge(city_lookup, on="City", how="left")

    unmatched = merged["latitude"].isna().sum() if "latitude" in merged.columns else 0
    if unmatched:
        logger.warning("Weather rows with no matching CSV city: %s", unmatched)

    logger.info("Merged city metadata into %s aggregated rows.", len(merged))
    return merged


# Export the merged daily weather DataFrame to a formatted Excel file
def export_excel_report(
    merged_df: pd.DataFrame, filepath: Path = EXCEL_REPORT_PATH
) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    sheet_name = "Daily Summary"

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        merged_df.to_excel(writer, sheet_name=sheet_name, index=False)
        worksheet = writer.sheets[sheet_name]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        for column_cells in worksheet.columns:
            max_length = max(
                (len(str(cell.value)) if cell.value is not None else 0)
                for cell in column_cells
            )
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(
                max_length + 2, 40
            )

    logger.info("Excel report saved to %s", filepath)
    return filepath


# Export cities exceeding the heat threshold as a JSON alert payload
def export_heat_alerts(
    merged_df: pd.DataFrame,
    filepath: Path = JSON_ALERTS_PATH,
    threshold_c: float = HEAT_ALERT_THRESHOLD_C,
) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    alert_columns = ["City", "Date", "Max_Temp_C"]
    if "country" in merged_df.columns:
        alert_columns.insert(1, "country")

    alerts = merged_df.loc[merged_df["Max_Temp_C"] > threshold_c, alert_columns].copy()
    alerts.to_json(filepath, orient="records", indent=2, date_format="iso")
    logger.info(
        "Wrote %s heat alerts (> %.1f°C) to %s", len(alerts), threshold_c, filepath
    )
    return filepath


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    try:
        cities = parse_cities_csv()
        logger.info("Normalized %s cities from %s", len(cities), RAW_CITIES_CSV.name)
        print(f"Normalized {len(cities)} cities from {RAW_CITIES_CSV.name}:")
        print(cities.to_string(index=False))

        logger.info("Beginning sequential weather data extraction...")
        start_sync = time.perf_counter()
        weather = fetch_weather_all_cities(cities)
        sync_duration = time.perf_counter() - start_sync
        fetched = sum(1 for result in weather if result["data"] is not None)
        logger.info("Fetched weather for %s of %s cities", fetched, len(weather))
        logger.info("Synchronous fetching completed in %.2f seconds.", sync_duration)
        print(f"Fetched weather for {fetched} of {len(weather)} cities.")
        print(f"Sequential execution time: {sync_duration:.2f} seconds.")

        hourly_df = hourly_forecasts_to_dataframe(weather)
        print(hourly_df.head())

        daily_summary = aggregate_daily_weather(hourly_df)
        daily_summary = merge_city_metadata(daily_summary, cities)
        print(daily_summary.head())

        excel_path = export_excel_report(daily_summary)
        print(f"Excel report saved to {excel_path}")

        alerts_path = export_heat_alerts(daily_summary)
        print(f"JSON heat alerts saved to {alerts_path}")
    except Exception:
        logger.exception("Pipeline execution failed.")
        raise


if __name__ == "__main__":
    main()
