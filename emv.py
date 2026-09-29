# pyright: ignore[reportAttributeAccessIssue]
"""Expected Monetary Value (EMV) decision analysis with 2D payoff tables."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

Matrix = list[list[float]]


@dataclass
class DecisionProblem:
    """A payoff table: payoff[alternative][state] -> monetary value."""

    alternatives: list[str]
    states: list[str]
    payoff: Matrix
    probabilities: list[float] | None = field(default=None)

    def __post_init__(self) -> None:
        rows_in = list(self.payoff)
        if not rows_in:
            raise ValueError("payoff must have at least one alternative")
        if any(len(row) != len(rows_in[0]) for row in rows_in):
            raise ValueError("every payoff row must have one value per state")
        self.payoff = np.asarray(rows_in, dtype=float)
        if self.payoff.ndim != 2:
            raise ValueError("payoff must be a 2D array of alternatives x states")
        rows, cols = self.payoff.shape
        if rows != len(self.alternatives) or cols != len(self.states):
            raise ValueError(
                f"payoff is {rows}x{cols} but {len(self.alternatives)} alternatives "
                f"and {len(self.states)} states were named"
            )
        if self.probabilities is not None:
            self.probabilities = np.asarray(self.probabilities, dtype=float)
            if self.probabilities.shape != (cols,):
                raise ValueError("probabilities must have one entry per state")
            if (self.probabilities < 0).any():
                raise ValueError("probabilities must be non-negative")
            total = self.probabilities.sum()
            if total <= 0:
                raise ValueError("probabilities must sum to a positive value")
            self.probabilities = self.probabilities / total

    # ---- core quantities -------------------------------------------------

    def emv(self) -> np.ndarray:
        """Expected monetary value of each alternative: payoff @ probabilities."""
        if self.probabilities is None:
            raise ValueError("no probabilities supplied: use uniform probabilities")
        return self.payoff @ self.probabilities

    def uniform_emv(self) -> np.ndarray:
        """Laplace criterion: assume all states equally likely."""
        return self.payoff.mean(axis=1)

    def maximax(self) -> np.ndarray:
        return self.payoff.max(axis=1)

    def maximin(self) -> np.ndarray:
        return self.payoff.min(axis=1)

    def minimax_regret(self) -> np.ndarray:
        """Worst-case shortfall against the best alternative in each state."""
        return (self.payoff.max(axis=0) - self.payoff).max(axis=1)

    # ---- reporting -------------------------------------------------------

    def analyze(self) -> dict:
        criteria: dict[str, tuple[np.ndarray, bool]] = {
            "maximax": (self.maximax(), True),
            "maximin": (self.maximin(), True),
            "minimax_regret": (self.minimax_regret(), False),
        }
        if self.probabilities is not None:
            criteria["emv"] = (self.emv(), True)
        else:
            criteria["laplace"] = (self.uniform_emv(), True)

        summary = {}
        for name, (values, maximize) in criteria.items():
            best = self._pick(values, maximize)
            summary[name] = {
                "values": dict(zip(self.alternatives, values.round(4).tolist())),
                "best": self.alternatives[best],
                "value": round(float(values[best]), 4),
            }

        primary = "emv" if self.probabilities is not None else "laplace"
        recommended = self.alternatives[self._pick(criteria[primary][0], True)]
        return {"alternatives": self.alternatives, "criteria": summary, "recommended": recommended}

    @staticmethod
    def _pick(values: np.ndarray, maximize: bool) -> int:
        return int(np.argmax(values) if maximize else np.argmin(values))

    def table(self) -> str:
        values = self.emv() if self.probabilities is not None else self.uniform_emv()
        headers = ["alternative", *self.states, "EMV"]
        rows = [
            [alt, *[f"{v:g}" for v in row], f"{values[i]:.2f}"]
            for i, (alt, row) in enumerate(zip(self.alternatives, self.payoff))
        ]
        widths = [
            max(len(str(r[c])) for r in [headers, *rows]) for c in range(len(headers))
        ]
        render = lambda cells: "  ".join(  # noqa: E731
            str(cell).ljust(w) for cell, w in zip(cells, widths)
        )
        sep = "  ".join("-" * w for w in widths)
        return "\n".join([render(headers), sep, *(render(r) for r in rows)])


def from_dict(data: dict) -> DecisionProblem:
    return DecisionProblem(
        alternatives=list(data["alternatives"]),
        states=list(data["states"]),
        payoff=data["payoff"],
        probabilities=data.get("probabilities"),
    )


def load_problem(path: str | None) -> DecisionProblem:
    if path:
        return from_dict(json.loads(Path(path).read_text()))
    return DecisionProblem(
        alternatives=["Build (in-house)", "Buy (supplier)", "Lease (contractor)"],
        states=["Demand high", "Demand medium", "Demand low"],
        payoff=[[120, 80, 40], [60, 60, 55], [90, 70, 20]],
        probabilities=[0.4, 0.35, 0.25],
    )


DEMO = """
Sample problem: a manufacturer must choose how to meet forecast demand.

                      high     medium   low
  Build (in-house)      120       80      40
  Buy (supplier)         60       60      55
  Lease (contractor)     90       70      20

  Values in thousands of currency units; state probabilities 0.40 / 0.35 / 0.25.
""".strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EMV decision analysis on a payoff table.")
    parser.add_argument("-f", "--file", help="JSON file holding the payoff table")
    parser.add_argument(
        "--equal", action="store_true", help="assume states are equally likely (Laplace)"
    )
    parser.add_argument(
        "--ui", action="store_true", help="open the interactive Qt interface"
    )
    parser.add_argument(
        "--size", metavar="WxH", help="UI window size: WxH (e.g. 1280x800) or a "
        "preset (Compact, Default, Wide)"
    )
    parser.add_argument(
        "--font-size", type=int, metavar="PT",
        help="UI text size in points, 7-40 (default: auto, from screen DPI)"
    )
    parser.add_argument(
        "--result-size", type=int, metavar="PT", help="results text size in points, 7-40"
    )
    parser.add_argument(
        "--density", choices=["Compact", "Normal", "Comfortable"],
        help="control padding density"
    )
    args = parser.parse_args(argv)

    problem = load_problem(args.file)
    if args.equal:
        problem.probabilities = None

    if args.ui:
        try:
            from emv_ui import main as ui_main
        except ImportError as exc:
            print(f"Cannot start the UI ({exc}). Install it with: uv sync", file=sys.stderr)
            return 1
        return ui_main(
            problem,
            size=args.size,
            font_pt=args.font_size,
            result_pt=args.result_size,
            density=args.density,
        )

    if not args.file:
        print(DEMO, "\n")

    print(problem.table(), "\n")
    report = problem.analyze()
    for name, data in report["criteria"].items():
        print(f"  {name:<14} best = {data['best']:<18} (value {data['value']})")
    print(f"\n  Recommended decision: {report['recommended']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
