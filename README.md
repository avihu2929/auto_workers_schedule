# Schedule

Enter workers and their weekly availability via a GUI; everything is saved to
`workers.json` for later scheduling steps.

## Run

```bash
.venv/bin/python main.py
```

(First time: `uv venv --python 3.13 --python-preference only-managed && uv pip install pyyaml pyside6`)
GUI is PySide6/Qt — Hebrew RTL input and display are supported natively on Linux and Windows.

## Usage

- **+ הוסף עובד** – add a worker by name (Hebrew or English)
- Select a worker in the list, click cells in the weekly grid to cycle
  availability (gray = can't work, plain = normal, yellow = "try")
- Every change saves automatically (no save button needed)
- Days/shift definitions are editable in `config.yaml`
