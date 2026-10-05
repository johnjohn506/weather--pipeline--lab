"""Weather data pipeline: parse and normalize dirty city CSV input."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Project paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = ROOT_DIR / "reports"
RAW_CITIES_CSV = DATA_DIR / "raw_cities.csv"

load_dotenv(ROOT_DIR / ".env")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    filename=ROOT_DIR / "pipeline.log",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.info("Pipeline configuration successfully loaded.")

# Column aliases for messy CSV headers
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


def normalize_header(name: object) -> str:
    """Normalize messy CSV headers to snake_case aliases."""
    cleaned = str(name).strip().lower()
    cleaned = re.sub(r"[\s\-]+", "_", cleaned)
    cleaned = re.sub(r"[^a-z0-9_]", "", cleaned)
    return COLUMN_ALIASES.get(cleaned, cleaned)


def normalize_city_name(value: object) -> str:
    """Clean a city label with regex search/replace, strip, and title-case."""
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


def normalize_country_name(value: object) -> str:
    """Clean a country label with the same string-normalization toolkit."""
    text = str(value).strip()
    text = re.sub(r"\.", "", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\d_]+", "", text)
    text = re.sub(r"\s+", " ", text)
    cleaned = text.strip().title()
    if cleaned.upper() == "USA":
        return "USA"
    return cleaned


def parse_cities_csv(filepath: str | Path | None = None) -> pd.DataFrame:
    """Parse the raw cities CSV and return normalized city coordinates."""
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


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    try:
        cities = parse_cities_csv()
        logger.info("Normalized %s cities from %s", len(cities), RAW_CITIES_CSV.name)
        print(f"Normalized {len(cities)} cities from {RAW_CITIES_CSV.name}:")
        print(cities.to_string(index=False))
    except Exception:
        logger.exception("Pipeline execution failed.")
        raise


if __name__ == "__main__":
    main()
