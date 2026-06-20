#!/usr/bin/env python3
"""
PyQt6 GUI wrapper for the GMS2 .yyz Parser (tool.py).
Lets the user browse for a .yyz file or project folder, run the parser,
and view the resulting JSON — all from a polished desktop UI.
"""

import json
import os
import sys
import traceback

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QProgressBar,
    QGroupBox,
)

# Import the core parser from tool.py (same directory)
import tool


# ---------------------------------------------------------------------------
# Worker thread — runs the parser off the UI thread
# ---------------------------------------------------------------------------
class ParserWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, input_path: str):
        super().__init__()
        self.input_path = input_path

    def run(self):
        try:
            import zipfile
            import tempfile

            input_path = self.input_path

            if zipfile.is_zipfile(input_path) or input_path.lower().endswith(".yyz"):
                with tempfile.TemporaryDirectory(prefix="gms2_") as tmp_dir:
                    with zipfile.ZipFile(input_path, "r") as zf:
                        zf.extractall(tmp_dir)
                    entries = os.listdir(tmp_dir)
                    yyp_at_root = any(e.endswith(".yyp") for e in entries)
                    if not yyp_at_root and len(entries) == 1:
                        project_root = os.path.join(tmp_dir, entries[0])
                    else:
                        project_root = tmp_dir
                    result = tool.process_project(project_root)
            elif os.path.isdir(input_path):
                result = tool.process_project(input_path)
            else:
                self.error.emit(f"'{input_path}' is neither a .yyz file nor a folder.")
                return

            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(traceback.format_exc())


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
STYLESHEET = """
QMainWindow {
    background-color: #1a1b2e;
}
QWidget#central {
    background-color: #1a1b2e;
}
QGroupBox {
    background-color: #242540;
    border: 1px solid #3a3b5c;
    border-radius: 10px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-size: 13px;
    font-weight: 600;
    color: #b8b9d4;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 6px;
    color: #8b8fd8;
}
QLabel {
    color: #c5c6e0;
    font-size: 13px;
}
QLabel#title {
    color: #e0e1ff;
    font-size: 22px;
    font-weight: 700;
}
QLabel#subtitle {
    color: #7a7ba8;
    font-size: 12px;
}
QLabel#statsLabel {
    color: #9d9ed8;
    font-size: 12px;
}
QLineEdit {
    background-color: #2a2b48;
    border: 1px solid #3a3b5c;
    border-radius: 6px;
    padding: 8px 12px;
    color: #e0e1ff;
    font-size: 13px;
    selection-background-color: #5c5dff;
}
QLineEdit:focus {
    border-color: #6c6dff;
}
QPushButton {
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    border: none;
}
QPushButton#browseFileBtn, QPushButton#browseFolderBtn {
    background-color: #2e2f52;
    color: #b0b1e0;
    border: 1px solid #3a3b5c;
}
QPushButton#browseFileBtn:hover, QPushButton#browseFolderBtn:hover {
    background-color: #3a3b5c;
    color: #e0e1ff;
}
QPushButton#runBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #5c5dff, stop:1 #8b5cf6);
    color: white;
    padding: 10px 32px;
    font-size: 14px;
    border-radius: 8px;
}
QPushButton#runBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #6c6dff, stop:1 #9b6cf6);
}
QPushButton#runBtn:disabled {
    background: #3a3b5c;
    color: #6a6b8c;
}
QPushButton#saveBtn {
    background-color: #1a6b4a;
    color: #c0ffd8;
    border: 1px solid #2a8b5a;
}
QPushButton#saveBtn:hover {
    background-color: #2a8b5a;
}
QPushButton#saveBtn:disabled {
    background-color: #2a2b48;
    color: #5a5b7c;
    border-color: #3a3b5c;
}
QTextEdit {
    background-color: #1e1f38;
    border: 1px solid #3a3b5c;
    border-radius: 8px;
    padding: 10px;
    color: #d0d1ee;
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    selection-background-color: #5c5dff;
}
QProgressBar {
    background-color: #2a2b48;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #5c5dff, stop:1 #8b5cf6);
    border-radius: 4px;
}
QSplitter::handle {
    background-color: #3a3b5c;
    height: 2px;
}
"""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GMS2 Project Parser")
        self.setMinimumSize(820, 620)
        self.resize(960, 700)
        self._result_data = None
        self._worker = None

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(16)

        # ---- Header ----
        title = QLabel("GMS2 Project Parser", objectName="title")
        subtitle = QLabel(
            "Extract architecture, code & interactions from .yyz files",
            objectName="subtitle",
        )
        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)

        # ---- Input group ----
        input_group = QGroupBox("Input")
        input_lay = QVBoxLayout(input_group)
        input_lay.setSpacing(10)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Path to .yyz file or project folder...")
        path_row.addWidget(self.path_edit, 1)

        btn_file = QPushButton("Open .yyz", objectName="browseFileBtn")
        btn_file.clicked.connect(self._browse_file)
        path_row.addWidget(btn_file)

        btn_folder = QPushButton("Open Folder", objectName="browseFolderBtn")
        btn_folder.clicked.connect(self._browse_folder)
        path_row.addWidget(btn_folder)

        input_lay.addLayout(path_row)

        # Run + progress row
        run_row = QHBoxLayout()
        self.run_btn = QPushButton("▶  Parse Project", objectName="runBtn")
        self.run_btn.clicked.connect(self._run_parser)
        run_row.addWidget(self.run_btn)
        run_row.addStretch()

        self.stats_label = QLabel("", objectName="statsLabel")
        run_row.addWidget(self.stats_label)

        input_lay.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        input_lay.addWidget(self.progress)

        root_layout.addWidget(input_group)

        # ---- Output group ----
        output_group = QGroupBox("Output JSON")
        output_lay = QVBoxLayout(output_group)
        output_lay.setSpacing(8)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("Parsed JSON will appear here...")
        output_lay.addWidget(self.output_edit, 1)

        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_btn = QPushButton("💾  Save JSON", objectName="saveBtn")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_json)
        save_row.addWidget(self.save_btn)
        output_lay.addLayout(save_row)

        root_layout.addWidget(output_group, 1)

    # ---- Slots ----

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select .yyz File",
            "",
            "GameMaker Archives (*.yyz);;All Files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if path:
            self.path_edit.setText(path)

    def _run_parser(self):
        input_path = self.path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(self, "No Input", "Please select a .yyz file or project folder first.")
            return
        if not os.path.exists(input_path):
            QMessageBox.warning(self, "Not Found", f"Path does not exist:\n{input_path}")
            return

        self.run_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.output_edit.clear()
        self.stats_label.setText("Parsing...")
        self.progress.setVisible(True)
        self._result_data = None

        self._worker = ParserWorker(input_path)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, result: dict):
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self._result_data = result

        obj_count = len(result.get("objects", {}))
        self.stats_label.setText(
            f"✔ {obj_count} object(s) from \"{result.get('project_name', '?')}\""
        )

        pretty = json.dumps(result, indent=2, ensure_ascii=False)
        self.output_edit.setPlainText(pretty)
        self.save_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.stats_label.setText("Error")
        QMessageBox.critical(self, "Parser Error", msg)

    def _save_json(self):
        if self._result_data is None:
            return
        default_name = self._result_data.get("project_name", "output") + "_parsed.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save JSON",
            default_name,
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._result_data, f, indent=2, ensure_ascii=False)
            self.stats_label.setText(f"Saved → {os.path.basename(path)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    # Set dark palette as base
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1a1b2e"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#c5c6e0"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1e1f38"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e0e1ff"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
