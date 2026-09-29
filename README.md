# discrete — EMV decision analysis

Expected Monetary Value analysis over a payoff table, with a Qt 6 interface.

## Run

```bash
uv sync                                     # once, installs PySide6
uv run emv.py                               # console report
uv run emv.py --ui                          # Qt interface
uv run emv.py --ui --size 1280x800 --font-size 16 --density Compact
uv run emv.py --ui -f problem.json          # load a saved payoff table
```

Console output only (no Qt needed):

```bash
uv run emv.py --equal                       # Laplace criterion instead of EMV
```

## Nix

Qt's shared libraries are not on the interpreter's search path on Nix, so use the
provided shell:

```bash
nix-shell            # or: nix develop
uv sync
uv run emv.py --ui
```

`flake.nix` additionally exposes a `discrete` package. As a fallback, the app
`dlopen`s any missing Qt library it can find in `/nix/store` (see `import_qt` in
`emv_ui.py`), so it usually runs even outside the shell.

## What it computes

For each alternative, over the states of nature:

| criterion | rule |
| --- | --- |
| `emv` | Σ P(state) · payoff — the recommended decision |
| `laplace` | mean payoff (used when no probabilities are given) |
| `maximax` | best case |
| `maximin` | worst case |
| `minimax_regret` | smallest worst-case regret |

## Files

- `emv.py` — model (`DecisionProblem`), criteria, and the CLI
- `emv_ui.py` — PySide6 window: editable table, live results, font size and density controls
- `pyproject.toml` — depends on `pyside6`

## Input file format

```json
{
  "alternatives": ["Build", "Buy", "Lease"],
  "states": ["high", "medium", "low"],
  "payoff": [[120, 80, 40], [60, 60, 55], [90, 70, 20]],
  "probabilities": [0.4, 0.35, 0.25]
}
```

`payoff[alternative][state]`. `probabilities` is optional; if omitted or empty the
Laplace criterion is used. Values are in any consistent currency unit.

## UI notes

- Text size, results text size, and density are applied at runtime only — nothing is
  written to disk. The default text size scales with the screen's logical DPI.
- `Ctrl++` / `Ctrl+-` change the text size, `Ctrl+0` resets it, `Ctrl+R` recomputes.
- Sizes are not persisted; pass `--size` / `--font-size` to start from a given size.
