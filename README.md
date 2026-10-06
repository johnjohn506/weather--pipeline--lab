# Weather Analytics & Alerting Pipeline

An automated Python pipeline that extracts, cleans, transforms, and reports global forecast data from the [Open-Meteo](https://api.open-meteo.com/v1/forecast) REST API. It demonstrates CSV text normalization with regular expressions, `httpx` API integration, pandas aggregation, Excel and JSON reporting, offline pytest coverage with `unittest.mock`, and GitHub Actions CI with Ruff.

## Project structure

```text
weather--pipeline--lab/
├── .github/workflows/ci.yml   # GitHub Actions: Ruff + pytest
├── data/raw_cities.csv        # Raw input with dirty city formatting
├── reports/                   # Generated Excel and JSON (gitignored)
├── src/
│   ├── __init__.py
│   └── pipeline.py            # Pipeline entry point
├── tests/test_pipeline.py     # Offline unit tests
├── .env                       # Local config (gitignored)
├── .gitignore
├── pyproject.toml
├── uv.lock
└── README.md
```

## Features

- **Environment and packages:** Managed with `uv`, `pyproject.toml`, and `uv.lock`.
- **Data cleaning:** Regular expressions plus `strip()` and title-case normalize messy city names.
- **API extraction:** Sequential Open-Meteo requests for hourly `temperature_2m` and `precipitation` with `timezone=auto`.
- **Transformation:** Hourly JSON is loaded into pandas, timestamps are converted to datetime, and daily max temperature and precipitation are aggregated per city.
- **Reporting:** Formatted Excel summary (`reports/weather_summary.xlsx`) and JSON heat alerts (`reports/alerts.json`) for days above 30°C.
- **Logging:** `LOG_LEVEL` is read from `.env`; INFO and ERROR events go to `pipeline.log`.
- **Testing and CI:** Pytest mocks the API so tests run offline. GitHub Actions runs Ruff and pytest on pull requests.

## Prerequisites

Install [uv](https://docs.astral.sh/uv/):

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Installation

```powershell
git clone https://github.com/johnjohn506/weather--pipeline--lab.git
cd weather--pipeline--lab
uv sync
```

Create a `.env` file in the project root (this file is gitignored):

```env
WEATHER_UNIT=celsius
MAX_RETRIES=3
LOG_LEVEL=INFO
ALERT_THRESHOLD_C=25
```

## Run the pipeline

```powershell
uv run python src/pipeline.py
```

When it finishes:

1. Execution details are written to `pipeline.log`.
2. The daily weather summary is saved to `reports/weather_summary.xlsx`.
3. City-days with a maximum temperature above 30°C are saved to `reports/alerts.json`.

The pipeline needs network access only for the live Open-Meteo fetch. Generated reports stay local because `/reports` and `*.log` are gitignored.

## Testing and code quality

Run the test suite offline (Open-Meteo is mocked):

```powershell
uv run pytest
```

Ruff checks:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run ruff format .
```

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main` and `integration`. Each run:

1. Sets up Python 3.12 and `uv` on Ubuntu.
2. Installs dependencies with `uv sync`.
3. Runs `uv run ruff format --check .` and `uv run ruff check .`.
4. Runs `uv run pytest`.
