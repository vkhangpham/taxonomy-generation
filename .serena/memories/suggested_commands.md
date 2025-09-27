# Suggested Commands
- `python -m venv .venv && source .venv/bin/activate` – create/activate a local virtual environment (macOS defaults).
- `pip install -e ".[dev]"` – install the package with dev extras (pytest, black, ruff).
- `python -m pytest` – run the unit test suite (`tests/`).
- `ruff check src tests` – lint the codebase with Ruff.
- `black src tests` – format Python sources using Black.
- `python main.py` – exercise the current placeholder CLI entrypoint.
- `python -m taxonomy.config.settings --help` – view configuration CLI flags (`Settings.from_args`).
- `TAXONOMY_SETTINGS__random_seed=123 python -m pytest` – example of overriding settings via environment variables during runs.