# Crypto Radar Agent

Python-based MVP scaffold for a Binance Crypto Radar Agent.

This project is intentionally read-only with respect to trading. It uses Binance public market data only and does not require private Binance API keys.

## Requirements

- Python 3.12+
- Binance public market-data access only
- No auto-trading
- No private Binance API keys

## Project Structure

```text
crypto-radar-agent/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── binance/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   └── symbols.py
│   ├── indicators/
│   │   ├── __init__.py
│   │   ├── momentum.py
│   │   ├── volume.py
│   │   └── breakout.py
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── opportunity_score.py
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── telegram.py
│   └── utils/
│       ├── __init__.py
│       └── logger.py
├── tests/
│   └── test_scoring.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Run the app:

```powershell
python -m app.main
```

Run tests:

```powershell
python -m pytest
```

## Supabase Paper Trade Columns

The app auto-adds these columns when Supabase storage initializes. If you need
to run the migration manually, use:

```sql
alter table paper_trades add column if not exists alert_type text;
alter table paper_trades add column if not exists trade_plan_type text;
alter table paper_trades add column if not exists strategy_name text;
```
