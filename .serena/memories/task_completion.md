# Task Completion Checklist
- Re-run `python -m pytest` to confirm unit tests pass after changes.
- Execute `ruff check src tests` and address lint issues (or document intentional ignores).
- Format touched Python files with `black` to keep style consistent.
- If configuration or policy files changed, verify overrides by instantiating `Settings()` and checking key attributes in a REPL or quick script.
- Update relevant docs under `docs/` or `README.md` whenever functional behavior or policies shift.
- Ensure any new prompts/policies are stored under config files rather than inline strings before submitting work.