"""Qt 6 (PySide6) interface for the EMV decision analysis program."""

from __future__ import annotations

import ctypes
import glob
import importlib
import os
import json
import re
import sys
from pathlib import Path

# Qt's shared libraries live outside the interpreter's search path on Nix-like
# systems; resolve them from /nix/store when the plain import fails.
MISSING_LIB = re.compile(r"([\w.+-]+\.so[\w.]*)")


def _is_64bit(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(5)[4] == 2
    except OSError:
        return False


def find_lib(name: str) -> str | None:
    """Locate a shared library the way the dynamic loader would, plus /nix/store."""
    try:
        ctypes.CDLL(name, mode=ctypes.RTLD_GLOBAL)
        return name
    except OSError:
        pass
    for path in sorted(glob.glob(f"/nix/store/*/{name}") + glob.glob(f"/nix/store/*/lib/{name}")):
        if not _is_64bit(path):
            continue
        try:
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            return path
        except OSError:
            continue
    return None


def preload_lib(name: str) -> bool:
    return find_lib(name) is not None


# libraries the Qt platform plugins dlopen preloaded before QApplication starts,
# because a plugin load failure is a hard qFatal abort that Python cannot catch
PLATFORM_PLUGIN_LIBS = (
    "libstdc++.so.6", "libgcc_s.so.1", "libz.so.1", "libzstd.so.1",
    "libxkbcommon.so.0", "libxkbcommon-x11.so.0", "libX11.so.6", "libX11-xcb.so.1",
    "libXcursor.so.1", "libXrandr.so.2", "libXinerama.so.1", "libXi.so.6",
    "libxcb.so.1", "libxcb-cursor.so.0", "libxcb-icccm.so.4", "libxcb-image.so.0",
    "libxcb-keysyms.so.1", "libxcb-render-util.so.0", "libxcb-util.so.1", "libxcb-randr.so.0", "libxcb-shape.so.0", "libxcb-shm.so.0", "libxcb-sync.so.1", "libxcb-xfixes.so.0", "libxcb-xkb.so.1", "libXss.so.1",
    "libxcb-xkb.so.1", "libXrender.so.1", "libXext.so.6", "libXfixes.so.3",
    "libSM.so.6", "libICE.so.6",
    "libwayland-client.so.0", "libwayland-cursor.so.0", "libwayland-egl.so.1",
)

# Qt aborts (qFatal) when no platform plugin loads, so check the common causes first
PLATFORM_LIB_HINTS = {
    "xcb": ("libxcb-cursor.so.0", "libxkbcommon-x11.so.0", "libX11-xcb.so.1"),
    "wayland": ("libwayland-client.so.0", "libwayland-cursor.so.0"),
}


def display_problem() -> str | None:
    """Return a human-readable reason the Qt platform plugin may fail, or None."""
    platform = os.environ.get("QT_QPA_PLATFORM", "").split(":")[0]
    if not platform:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return "no DISPLAY or WAYLAND_DISPLAY: set QT_QPA_PLATFORM=offscreen to run headless"
        platform = "wayland" if os.environ.get("WAYLAND_DISPLAY") else "xcb"
    if platform == "xcb" and not os.environ.get("DISPLAY"):
        return "QT_QPA_PLATFORM=xcb but DISPLAY is unset: export DISPLAY=:0 (or use QT_QPA_PLATFORM=offscreen)"
    if platform.startswith("wayland") and not os.environ.get("WAYLAND_DISPLAY"):
        return f"QT_QPA_PLATFORM={platform} but WAYLAND_DISPLAY is unset: use QT_QPA_PLATFORM=xcb under XWayland"
    for lib in PLATFORM_LIB_HINTS.get(platform, ()):
        if find_lib(lib) is None:
            missing = [n for n in PLATFORM_LIB_HINTS[platform] if find_lib(n) is None]
            return (
                f"QT_QPA_PLATFORM={platform} needs {', '.join(missing)}; "
                "run inside the provided Nix shell (nix-shell) which provides them"
            )
    return None


def import_qt(max_rounds: int = 20) -> tuple[list[str], list[str]]:
    """Import PySide6, preloading each missing shared library as it comes up."""
    preloaded: list[str] = []
    for _ in range(max_rounds):
        try:
            QtCore = importlib.import_module("PySide6.QtCore")
            QtGui = importlib.import_module("PySide6.QtGui")
            QtWidgets = importlib.import_module("PySide6.QtWidgets")
            return QtCore, QtGui, QtWidgets, preloaded
        except ImportError as exc:
            found = MISSING_LIB.search(str(exc))
            if not found or not preload_lib(found.group(1)):
                raise ImportError(
                    f"{exc}\nInstall Qt with: uv sync (on Nix also add pkgs.libglvnd "
                    "and pkgs.glib to your environment)"
                ) from exc
            preloaded.append(found.group(1))
    raise ImportError("could not resolve Qt's shared libraries")


QtCore, QtGui, QtWidgets, PRELOADED_LIBS = import_qt()

from emv import DecisionProblem

SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "Compact": (820, 560),
    "Default": (1040, 700),
    "Wide": (1400, 860),
}
MIN_SIZE = (640, 460)

# padding in px around buttons/inputs, keyed by density
DENSITY_PADDING = {"Compact": 2, "Normal": 6, "Comfortable": 11}
# Qt rescales everything from the application font, so a point size is all we need
FONT_PT_RANGE = (7, 40)
DEFAULT_PT_AT_96DPI = 11
PREFERRED_FAMILIES = (
    "Inter", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Ubuntu",
    "Segoe UI", "Helvetica Neue", "Helvetica", "Arial", "Cantarell",
)


def pick_family() -> str:
    available = set(QtGui.QFontDatabase.families())
    for name in PREFERRED_FAMILIES:
        if name in available:
            return name
    return QtWidgets.QApplication.font().family()


def auto_font_pt() -> int:
    """Scale the default text size with the screen's real DPI."""
    screen = QtGui.QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen else 96.0
    lo, hi = FONT_PT_RANGE
    return min(hi, max(lo, round(DEFAULT_PT_AT_96DPI * dpi / 96)))


def parse_size(size: str | tuple[int, int] | None) -> tuple[int, int] | None:
    if size is None:
        return None
    if isinstance(size, tuple):
        return size
    preset = SIZE_PRESETS.get(size.title())
    if preset:
        return preset
    try:
        w, h = (int(v) for v in size.lower().replace("x", " ").split())
    except ValueError:
        raise ValueError(f"bad size {size!r}: use WxH, e.g. 1280x800") from None
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        raise ValueError(f"size must be at least {MIN_SIZE[0]}x{MIN_SIZE[1]}")
    return w, h


class EmvWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        problem: DecisionProblem | None = None,
        size: str | tuple[int, int] | None = None,
        font_pt: int | None = None,
        result_pt: int | None = None,
        density: str | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("EMV Decision Analysis")
        self.path: Path | None = None
        self._loading = False

        p = problem or DecisionProblem(
            alternatives=["Alternative A", "Alternative B", "Alternative C"],
            states=["State 1", "State 2", "State 3"],
            payoff=[[120, 80, 40], [60, 60, 55], [90, 70, 20]],
            probabilities=[0.4, 0.35, 0.25],
        )
        self.alts: list[str] = list(p.alternatives)
        self.states: list[str] = list(p.states)
        self.payoff: list[list[float]] = [list(map(float, row)) for row in p.payoff]
        self.probs: list[float | None] = (
            list(p.probabilities) if p.probabilities is not None else [None] * len(self.states)
        )

        self.font_pt = int(font_pt or auto_font_pt())
        self.result_pt = int(result_pt or self.font_pt)
        self.density = density if density in DENSITY_PADDING else "Normal"
        self.family = pick_family()

        self._build()
        self.apply_appearance()

        w, h = parse_size(size) or SIZE_PRESETS["Default"]
        self.resize(w, h)
        self.setMinimumSize(*MIN_SIZE)
        self.rebuild_table()
        self.recompute()

    # ---- layout ----------------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget(self)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        files = QtWidgets.QHBoxLayout()
        self.act_open = QtGui.QAction("Open JSON…", self)
        self.act_open.triggered.connect(self.open_json)
        self.act_save = QtGui.QAction("Save JSON…", self)
        self.act_save.triggered.connect(self.save_json)
        self.act_recompute = QtGui.QAction("Recompute", self)
        self.act_recompute.setShortcut(QtGui.QKeySequence("Ctrl+R"))
        self.act_recompute.triggered.connect(self.recompute)
        self.act_zoom_in = QtGui.QAction("Larger text", self)
        self.act_zoom_in.setShortcut(QtGui.QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_in.triggered.connect(lambda: self.set_font_pt(self.font_pt + 1))
        self.act_zoom_out = QtGui.QAction("Smaller text", self)
        self.act_zoom_out.setShortcut(QtGui.QKeySequence.StandardKey.ZoomOut)
        self.act_zoom_out.triggered.connect(lambda: self.set_font_pt(self.font_pt - 1))
        self.act_reset = QtGui.QAction("Reset text size", self)
        self.act_reset.setShortcut(QtGui.QKeySequence("Ctrl+0"))
        self.act_reset.triggered.connect(lambda: self.set_font_pt(auto_font_pt()))
        for action in (self.act_open, self.act_save, self.act_recompute,
                       self.act_zoom_in, self.act_zoom_out, self.act_reset):
            self.addAction(action)
            files.addWidget(self.action_button(action))
        files.addStretch(1)
        outer.addLayout(files)

        look = QtWidgets.QHBoxLayout()
        look.addWidget(QtWidgets.QLabel("Text size:"))
        self.font_spin = QtWidgets.QSpinBox(self)
        self.font_spin.setRange(*FONT_PT_RANGE)
        self.font_spin.setSuffix(" pt")
        self.font_spin.setValue(self.font_pt)
        self.font_spin.valueChanged.connect(self.set_font_pt)
        look.addWidget(self.font_spin)
        auto_button = QtWidgets.QPushButton("Auto", self, clicked=self.set_auto_font)
        look.addWidget(auto_button)
        look.addSpacing(12)
        look.addWidget(QtWidgets.QLabel("Results text:"))
        self.result_spin = QtWidgets.QSpinBox(self)
        self.result_spin.setRange(*FONT_PT_RANGE)
        self.result_spin.setSuffix(" pt")
        self.result_spin.setValue(self.result_pt)
        self.result_spin.valueChanged.connect(self.set_result_pt)
        look.addWidget(self.result_spin)
        look.addSpacing(12)
        look.addWidget(QtWidgets.QLabel("Density:"))
        self.density_box = QtWidgets.QComboBox(self)
        self.density_box.addItems(list(DENSITY_PADDING))
        self.density_box.setCurrentText(self.density)
        self.density_box.currentTextChanged.connect(self.set_density)
        look.addWidget(self.density_box)
        look.addStretch(1)
        self.font_label = QtWidgets.QLabel("")
        self.font_label.setStyleSheet("color: #b00;")
        look.addWidget(self.font_label)
        outer.addLayout(look)

        edit = QtWidgets.QHBoxLayout()
        for text, slot in (
            ("+ alternative", self.add_alternative),
            ("- alternative", self.remove_alternative),
            ("+ state", self.add_state),
            ("- state", self.remove_state),
        ):
            edit.addWidget(QtWidgets.QPushButton(text, self, clicked=slot))
        edit.addStretch(1)
        self.criteria_box = QtWidgets.QComboBox(self)
        self.criteria_box.addItems(["All criteria", "EMV only", "EMV + minimax regret"])
        edit.addWidget(QtWidgets.QLabel("Show:"))
        edit.addWidget(self.criteria_box)
        outer.addLayout(edit)

        self.table = QtWidgets.QTableWidget(0, 0, self)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.itemSelectionChanged.connect(self.sync_buttons)
        outer.addWidget(self.table, 1)

        results = QtWidgets.QGroupBox("Results", self)
        vbox = QtWidgets.QVBoxLayout(results)
        self.results = QtWidgets.QPlainTextEdit(results)
        self.results.setReadOnly(True)
        self.results.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        vbox.addWidget(self.results)
        outer.addWidget(results, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Edit the table; results update as you type.")

    def action_button(self, action: QtGui.QAction) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(action.text(), self)
        button.clicked.connect(action.trigger)
        return button

    # ---- appearance ------------------------------------------------------

    def apply_appearance(self) -> None:
        font = QtGui.QFont(self.family, self.font_pt)
        QtWidgets.QApplication.instance().setFont(font)
        pad = DENSITY_PADDING[self.density]
        self.setStyleSheet(
            f"QPushButton, QToolButton {{ padding: {pad}px {pad * 2}px; }}"
            f"QComboBox, QSpinBox {{ padding: {max(1, pad // 2)}px {pad}px; }}"
            f"QTableView {{ gridline-color: #ddd; }}"
        )
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(self.result_pt)
        self.results.setFont(mono)
        self.font_spin.blockSignals(True)
        self.font_spin.setValue(self.font_pt)
        self.font_spin.blockSignals(False)
        self.result_spin.blockSignals(True)
        self.result_spin.setValue(self.result_pt)
        self.result_spin.blockSignals(False)
        self.font_label.setText(
            "" if self.family else "no scalable font found: install DejaVu/Liberation"
        )

    def set_font_pt(self, value: int) -> None:
        lo, hi = FONT_PT_RANGE
        self.font_pt = min(hi, max(lo, int(value)))
        self.apply_appearance()

    def set_result_pt(self, value: int) -> None:
        lo, hi = FONT_PT_RANGE
        self.result_pt = min(hi, max(lo, int(value)))
        self.apply_appearance()

    def set_density(self, name: str) -> None:
        if name in DENSITY_PADDING:
            self.density = name
            self.apply_appearance()

    def set_auto_font(self) -> None:
        self.set_result_pt(auto_font_pt())
        self.set_font_pt(auto_font_pt())

    # ---- table -----------------------------------------------------------

    def rebuild_table(self) -> None:
        self._loading = True
        rows, cols = len(self.alts), len(self.states) + 3
        self.table.clear()
        self.table.setRowCount(rows)
        self.table.setColumnCount(cols)
        headers = ["Alternative", *self.states, "P(state)", "EMV"]
        self.table.setHorizontalHeaderLabels(headers)
        prob_col, emv_col = len(self.states) + 1, len(self.states) + 2
        for r, alt in enumerate(self.alts):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(alt))
            for c, value in enumerate(self.payoff[r], start=1):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(f"{value:g}"))
            # one probability per state, shown once in the first row
            prob = self.probs[0] if r == 0 else None
            self.table.setItem(
                r, prob_col, QtWidgets.QTableWidgetItem("" if prob is None else f"{prob:g}")
            )
            self.table.setItem(r, emv_col, QtWidgets.QTableWidgetItem(""))
        for r in range(1, rows):
            cell = self.table.item(r, prob_col)
            cell.setFlags(cell.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            cell.setForeground(QtGui.QBrush(QtGui.QColor("#aaa")))
            cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        for r in range(rows):
            item = self.table.item(r, emv_col)
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                 | QtCore.Qt.AlignmentFlag.AlignVCenter)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        self._loading = False
        self.sync_buttons()

    def on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._loading:
            return
        r, c = item.row(), item.column()
        text = item.text().strip()
        if c == 0:
            self.alts[r] = text or f"Alt {r + 1}"
        elif c == len(self.states) + 1 and r == 0:
            self.probs[0] = self._as_float(text)
        else:
            self.payoff[r][c - 1] = self._as_float(text) or 0.0
        self.recompute()

    @staticmethod
    def _as_float(text: str) -> float | None:
        try:
            return float(text)
        except ValueError:
            return None

    def sync_buttons(self) -> None:
        self.statusBar().showMessage(
            f"{len(self.alts)} alternatives x {len(self.states)} states"
        )

    def add_alternative(self) -> None:
        self.alts.append(f"Alternative {chr(65 + len(self.alts))}")
        self.payoff.append([0.0] * len(self.states))
        self.rebuild_table()

    def remove_alternative(self) -> None:
        if len(self.alts) <= 1:
            self.statusBar().showMessage("keep at least one alternative", 4000)
            return
        index = self.table.currentRow()
        if index < 0:
            index = len(self.alts) - 1
        self.alts.pop(index)
        self.payoff.pop(index)
        self.rebuild_table()

    def add_state(self) -> None:
        self.states.append(f"State {len(self.states) + 1}")
        self.probs.append(0.0)
        for row in self.payoff:
            row.append(0.0)
        self.rebuild_table()

    def remove_state(self) -> None:
        index = self.table.currentColumn()
        if len(self.states) <= 1 or index <= 0 or index > len(self.states):
            return
        self.states.pop(index - 1)
        self.probs.pop(index - 1)
        for row in self.payoff:
            row.pop(index - 1)
        self.rebuild_table()

    # ---- model -----------------------------------------------------------

    def collect(self) -> DecisionProblem:
        raw = [p for p in self.probs if p is not None]
        return DecisionProblem(
            alternatives=[a or f"Alt {i + 1}" for i, a in enumerate(self.alts)],
            states=[s or f"State {i + 1}" for i, s in enumerate(self.states)],
            payoff=[list(row) for row in self.payoff],
            probabilities=raw if raw else None,
        )

    def recompute(self) -> None:
        try:
            problem = self.collect()
        except ValueError as exc:
            self.results.setPlainText(f"Invalid input: {exc}")
            return
        report = problem.analyze()
        text = [problem.table(), ""]
        wanted = {
            "All criteria": None,
            "EMV only": ["emv", "laplace"],
            "EMV + minimax regret": ["emv", "laplace", "minimax_regret"],
        }[self.criteria_box.currentText()]
        for name, data in report["criteria"].items():
            if wanted and name not in wanted:
                continue
            text.append(f"  {name:<14} best = {data['best']}  ({data['value']})")
        text.append("")
        text.append(f"  Recommended decision: {report['recommended']}")
        self.results.setPlainText("\n".join(text))
        values = (
            problem.emv()
            if problem.probabilities is not None
            else problem.uniform_emv()
        )
        emv_col = len(self.states) + 2
        self._loading = True
        for r, value in enumerate(values):
            self.table.item(r, emv_col).setText(f"{value:.2f}")
        self._loading = False

    # ---- files -----------------------------------------------------------

    def open_json(self) -> None:
        name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open payoff table", "", "JSON files (*.json)"
        )
        if not name:
            return
        data = json.loads(Path(name).read_text())
        p = DecisionProblem(
            alternatives=list(data["alternatives"]),
            states=list(data["states"]),
            payoff=data["payoff"],
            probabilities=data.get("probabilities"),
        )
        self.alts = list(p.alternatives)
        self.states = list(p.states)
        self.payoff = [list(map(float, row)) for row in p.payoff]
        self.probs = list(p.probabilities) if p.probabilities is not None else [None] * len(self.states)
        self.path = Path(name)
        self.setWindowTitle(f"EMV Decision Analysis - {Path(name).name}")
        self.rebuild_table()

    def save_json(self) -> None:
        name, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save payoff table", "problem.json", "JSON files (*.json)"
        )
        if not name:
            return
        try:
            p = self.collect()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid input", str(exc))
            return
        Path(name).write_text(
            json.dumps(
                {
                    "alternatives": p.alternatives,
                    "states": p.states,
                    "payoff": p.payoff,
                    "probabilities": p.probabilities,
                },
                indent=2,
            )
        )
        self.path = Path(name)
        self.statusBar().showMessage(f"Saved {name}", 4000)


def main(
    problem: DecisionProblem | None = None,
    size: str | None = None,
    font_pt: int | None = None,
    result_pt: int | None = None,
    density: str | None = None,
) -> int:
    try:
        w, h = parse_size(size) or SIZE_PRESETS["Default"]
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    for lib in PLATFORM_PLUGIN_LIBS:
        preload_lib(lib)
    problem = display_problem()
    if problem:
        print(f"Cannot open a window: {problem}", file=sys.stderr)
        return 3
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    window = EmvWindow(problem, size=(w, h), font_pt=font_pt, result_pt=result_pt, density=density)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
