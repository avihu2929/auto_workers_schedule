# Schedule

Enter workers and their weekly availability via a GUI; the built-in solver
(CP-SAT / OR-Tools) fits workers into shifts, honoring per-worker and
global rules. Everything saves automatically to `workers.json` /
`rules.json`.

## Windows exe

Built automatically by GitHub Actions on every push to `main`:

1. Open https://github.com/avihu2929/auto_workers_schedule/actions
2. Click the latest **build-windows** run (green)
3. Download the **schedule-windows** artifact from the run page's Artifacts section, unzip
4. Run `schedule.exe` — data files are created next to it on first run
   (requires no Python installation; SmartScreen may ask once: "More info → Run anyway")

## Run from source (dev)

```bash
.venv/bin/python main.py
```

(First time: `uv venv --python 3.13 --python-preference only-managed && uv pip install pyyaml pyside6 ortools`)
GUI is PySide6/Qt — Hebrew RTL input and display are supported natively on Linux and Windows.

## Usage

- **+ הוסף עובד** – add a worker by name (Hebrew or English)
- Select a worker in the list, click cells in the weekly grid to cycle
  availability (gray = can't work, plain = normal, yellow = "try")
- Every change saves automatically (no save button needed)
- Days/shift definitions are editable in `config.yaml`
