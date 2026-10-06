# SMC Trading Bot

An ongoing Python / MetaTrader 5 engineering project maintained by Thanatat Sareekham.

## Current source

- `smc_core_v24.py`: strategy configuration, indicators and setup/scoring logic
- `smc_bot_v24_live.py`: market data, broker connection, guards, state persistence and execution/position modules
- `_Archive/`: earlier development files

Both v24 files were verified against the local working files on 6 October 2026.

## Engineering areas

- Separate strategy core and runtime
- Multi-symbol market-data handling
- Connection recovery and broker clock synchronisation
- Spread and news guards
- Risk, execution and position-management classes
- SQLite state, cooldowns and an asynchronous database writer
- Graceful shutdown and runtime heartbeat

## Dependencies visible in source

Python, MetaTrader5, NumPy, Pandas and pytz. The strategy core also has optional Numba and SciPy paths. A reproducible dependency lock is not currently provided.

## Review approach

Start with static source review. `smc_bot_v24_live.py` includes broker execution code; do not run it against a funded account just to inspect the project. Use an isolated demo environment for runtime testing and verify its configuration independently.

## Project status

In development. This repository demonstrates implementation and architecture, not a claim of profitable trading, validated backtest returns or a completed independent safety audit.

## Data handling

Keep broker credentials, account databases, trading history, runtime logs, virtual environments and private market-data exports outside the repository.

## Portfolio

[More projects by Thanatat Sareekham](https://github.com/DewThanatat)
