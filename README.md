# Sustainability Tracker (Day 4) 🌍

A compact Streamlit app to log daily activities, estimate CO₂ emissions, visualize trends, and get actionable eco-tips. Optimized for one-page demos and PDF export.

## Quick Start

1) Install
- `pip install -r requirements.txt`

2) Optional: OpenAI key for AI tips
- PowerShell:
  - `$env:OPENAI_API_KEY="sk-..."`
- Or create a `.env` file (recommended):
  - Copy `.env.example` to `.env` and set `OPENAI_API_KEY=sk-...`
- If not set, tips fall back to a local rules-based generator.

3) Run
- `streamlit run app.py`

## Features

- Density toggle (Compact/Comfy) with URL persistence (`?density=Compact/Comfy`)
- Grouped inputs in expanders (Energy, Transport, Meals) with columns
- KPIs: Total, Δ vs. Yesterday, Streak
- Dashboard:
  - Category totals table + bar chart
  - Trend line (total kg CO₂)
  - Eco-tip and status
  - Badges
  - Mini sparklines (Energy, Transport, Meals) with 7-day delta metrics (green = down, red = up)
- Breakdown tab: per-activity emissions table
- History saved to `history.csv` (local CSV)
- Demo helpers in the header:
  - Prefill demos/presets (Demo values, No car day, Vegetarian day, Business trip)
  - Clear inputs
  - Reset layout
  - Copy shareable link (includes density)
  - Export PDF tips

## Usage Tips

- **Density and URL**  
  Use the Density toggle in the header. The setting is saved to session state and reflected in the URL.
- **Presets**  
  Open “Prefill demos/presets” and choose a scenario to quickly fill inputs.
- **Save & Trends**  
  Click “Calculate & Save” to append/update your entry for the selected date. Trend charts update after saving.
- **PDF Export**  
  Use the “Export PDF tips” popover in the header:  
  - Layout: Landscape  
  - Scale: 75–85%  
  - Margins: Narrow  
  For best results, use Compact density and collapsed expanders to fit on one page.

## Data

- File: `history.csv` in the project root
  - Upserted by date, sorted by date
  - Columns: date, activity inputs (e.g., `electricity_kwh`), `total_kg`
- Factors defined in `co2_engine.CO2_FACTORS`, aggregated into categories in `app.py:CATEGORY_MAP`.

## Tests

- Run all tests:
  - `pytest -q`
- Included test files:
  - `tests/test_co2_engine.py`
  - `tests/test_utils.py`
  - `tests/test_ai_tips.py`
  - `tests/test_app_module.py`

> ⚡ Note: Tests use mocking, so they run quickly and don’t require an OpenAI API key.

## CI (optional)

- GitHub Actions workflow runs:
  - `pip install -r requirements.txt`
  - `pytest`
  - Import check: `python -c "import app"`

## Troubleshooting

- **Query params deprecation**  
  Uses `st.query_params` (no experimental warnings).
- **No charts appearing**  
  Add at least one “Calculate & Save” entry.
- **AI tips**  
  If no API key or an API error occurs, the app automatically uses a local rules-based tip.  
  If you see a fallback message in the app, ensure `OPENAI_API_KEY` is set (via `.env` or environment) and valid.

## Secrets

- **.env workflow**  
  - Copy `.env.example` (safe to commit) → `.env` (local only) and add your real key:  
    - `OPENAI_API_KEY=sk-...`  
  - Loaded automatically in `ai_tips.py` via `python-dotenv`.
- **Install**  
  - `pip install python-dotenv` (already in requirements.txt).
- **Git ignore**  
  - `.env` is ignored via `.gitignore` so your key won’t be committed.
- **Validate**  
  - Run `git status` to confirm `.env` is untracked.
  - Launch the app and verify AI tips use GPT (no fallback message) when the key is present.

## Roadmap (post-Day 4)

- Add a 7-day baseline line to sparklines
- Tooltips on metrics/charts
- CSV-based preset import
- Accessibility improvements
- Refactor small helpers from `app.py` into `utils.py` for clarity
