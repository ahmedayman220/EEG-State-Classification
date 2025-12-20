#!/usr/bin/env python3
"""
Simple EEG GUI:
  - Connects to Arduino/ADS1115 over serial
  - Shows a live plot of Voltage
  - Saves all readings to CSV files for history
  - Can load & view old CSV recordings

Run:
    python eeg_gui.py
"""

from __future__ import annotations

import csv
import os
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Deque, Optional, Tuple, List, Any

import matplotlib

matplotlib.use("Qt5Agg")

import numpy as np  # noqa: E402
import serial  # noqa: E402
from matplotlib.backends.backend_qt5agg import (  # noqa: E402
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure  # noqa: E402

import joblib  # noqa: E402

from PyQt5.QtCore import QTimer, Qt  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QFrame,
    QCheckBox,
)
from PyQt5.QtGui import QPixmap, QFont  # noqa: E402

from eeg_features import extract_features, DEFAULT_FS


SERIAL_PORT = "/dev/cu.usbmodem214101"
BAUD_RATE = 9600
SAMPLES_TO_SHOW = 500
READ_TIMEOUT = 1.0
DATA_DIR = "data"
MODEL_DIR = "models"
MODEL_PATH = os.path.join(MODEL_DIR, "eeg_state_model.pkl")
CLASS_NAMES = {0: "Relaxed", 1: "Focused", 2: "Sleepy"}
CLASS_COLORS = {0: "green", 1: "blue", 2: "orange"}
WINDOW_SECONDS = 3.0  # seconds of data used for classification (moving average)


class SerialReader(threading.Thread):
    """
    Background thread that reads samples from the serial port and
    pushes them into a fixed-length buffer and CSV log.
    """

    def __init__(
        self,
        port: str,
        baud_rate: int,
        buffer: Deque[float],
        stop_event: threading.Event,
        csv_path: str,
    ) -> None:
        super().__init__(daemon=True)
        self._port = port
        self._baud_rate = baud_rate
        self._buffer = buffer
        self._stop_event = stop_event
        self._csv_path = csv_path
        self._ser: Optional[serial.Serial] = None

    def run(self) -> None:
        try:
            self._ser = serial.Serial(
                self._port,
                self._baud_rate,
                timeout=READ_TIMEOUT,
            )
            # Small delay to let the Arduino reset and start sending.
            time.sleep(2.0)
        except serial.SerialException as exc:
            print(f"[ERROR] Could not open serial port {self._port}: {exc}", file=sys.stderr)
            return

        print(f"[INFO] Reading from {self._port} at {self._baud_rate} baud...")

        # Open CSV file and write header
        os.makedirs(os.path.dirname(self._csv_path), exist_ok=True)
        with self._ser, open(self._csv_path, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_iso", "raw", "voltage"])

            while not self._stop_event.is_set():
                try:
                    line_bytes = self._ser.readline()
                    if not line_bytes:
                        continue

                    line = line_bytes.decode(errors="ignore").strip()
                    if not line:
                        continue

                    parsed = self._parse_line(line)
                    if parsed is None:
                        continue

                    raw_value, voltage = parsed
                    # Push voltage into buffer for plotting
                    self._buffer.append(voltage)

                    # Log to CSV with timestamp
                    ts = datetime.utcnow().isoformat()
                    writer.writerow([ts, raw_value, voltage])
                except serial.SerialException as exc:
                    print(f"[ERROR] Serial read error: {exc}", file=sys.stderr)
                    break
                except UnicodeDecodeError:
                    # Ignore malformed lines
                    continue

        print(f"[INFO] SerialReader stopped. Log saved to {self._csv_path}")

    @staticmethod
    def _parse_line(line: str) -> Optional[Tuple[Optional[int], float]]:
        """
        Parse a line of text coming from the Arduino.
        Expected ideal format from your sketch:
            "Raw: 1425\tVoltage: 1.87"

        Returns:
            (raw_value or None, voltage)
        """
        # Try to extract voltage
        voltage_match = re.search(r"Voltage:\s*([+-]?\d*\.?\d+)", line, re.IGNORECASE)
        # Try to extract raw
        raw_match = re.search(r"Raw:\s*(\d+)", line, re.IGNORECASE)

        voltage: Optional[float] = None
        raw_value: Optional[int] = None

        if voltage_match:
            try:
                voltage = float(voltage_match.group(1))
            except ValueError:
                voltage = None

        if raw_match:
            try:
                raw_value = int(raw_match.group(1))
            except ValueError:
                raw_value = None

        # If we didn't get voltage explicitly, fallback to first numeric token
        if voltage is None:
            number_match = re.search(r"([+-]?\d*\.?\d+)", line)
            if number_match:
                try:
                    voltage = float(number_match.group(1))
                except ValueError:
                    return None
            else:
                return None

        return raw_value, voltage


class MplCanvas(FigureCanvas):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        fig = Figure(figsize=(8, 6))
        # Top axis: live run, Bottom axis: history runs
        self.ax_live = fig.add_subplot(2, 1, 1)
        # Separate x-axis for history so it does not share scale with live
        self.ax_history = fig.add_subplot(2, 1, 2)
        # Add extra vertical space between the two graphs
        fig.subplots_adjust(hspace=0.4, top=0.95, bottom=0.08)
        super().__init__(fig)
        self.setParent(parent)


class HomeWindow(QMainWindow):
    """
    Simple start/home page showing project info, team members, logos,
    and a button to open the main EEG application.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EEG Project - Home")
        self.resize(900, 550)
        self.app_window: Optional[MainWindow] = None  # type: ignore[name-defined]

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        central.setLayout(layout)
        central.setStyleSheet(
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #eef2ff, stop:1 #f5f7fb);"
        )

        # Top logos row
        logos_layout = QHBoxLayout()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        left_logo_path = os.path.join(base_dir, "images", "faculty_logo.jpeg")
        right_logo_path = os.path.join(base_dir, "images", "department_logo.jpeg")

        left_logo = QLabel()
        right_logo = QLabel()

        left_pix = QPixmap(left_logo_path)
        if not left_pix.isNull():
            left_logo.setPixmap(left_pix.scaledToHeight(100, Qt.SmoothTransformation))

        right_pix = QPixmap(right_logo_path)
        if not right_pix.isNull():
            right_logo.setPixmap(right_pix.scaledToHeight(100, Qt.SmoothTransformation))

        left_logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        right_logo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        logos_layout.addWidget(left_logo, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        logos_layout.addStretch(1)
        logos_layout.addWidget(right_logo, alignment=Qt.AlignRight | Qt.AlignVCenter)
        logos_layout.setContentsMargins(0, 0, 0, 10)

        layout.addLayout(logos_layout)

        # Project title
        title_label = QLabel("EEG-Based Mental State Classification")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #1f2933; letter-spacing: 0.5px;"
        )
        title_label.setFont(QFont("Arial", 18, QFont.Bold))
        layout.addWidget(title_label)

        subtitle = QLabel("Benha Faculty of Engineering")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #52606d;")
        layout.addWidget(subtitle)

        # Team members and instructor (centered card)
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.StyledPanel)
        info_frame.setStyleSheet(
            "QFrame {"
            "  background-color: rgba(255,255,255,0.95);"
            "  border-radius: 12px;"
            "}"
        )

        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(30, 18, 30, 18)
        info_layout.setSpacing(6)

        students_label = QLabel(
            "Ahmed Ayman\n\n"
            "Alaa Ali\n\n"
            "Caroline Samir\n\n"
            "Mohamed Maher\n\n"
            "Yousef Hesham\n\n"
            "Mohamed El-Nady"
        )
        students_label.setAlignment(Qt.AlignCenter)
        students_label.setStyleSheet(
            "font-size: 18px; color: #1f2933; line-height: 1.6;"
        )

        instructor_label = QLabel("Instructor: Dr. Ashraf Mahrous")
        instructor_label.setAlignment(Qt.AlignCenter)
        instructor_label.setStyleSheet(
            "font-size: 16px; color: #1f2933; line-height: 1.4; "
            "font-weight: bold; margin-top: 12px;"
        )

        info_layout.addWidget(students_label, alignment=Qt.AlignCenter)
        info_layout.addWidget(instructor_label, alignment=Qt.AlignCenter)

        info_frame.setMaximumWidth(420)
        layout.addWidget(info_frame, alignment=Qt.AlignHCenter)

        # Spacer
        layout.addStretch(1)

        # Start button
        start_button = QPushButton("Start Application")
        start_button.setFixedWidth(200)
        start_button.setStyleSheet(
            "font-size: 14px; padding: 10px 18px; font-weight: bold;"
            "background-color: #2563eb; color: white; border-radius: 20px;"
            "border: none;"
            "box-shadow: 0px 4px 8px rgba(37,99,235,0.35);"
            "outline: none;"
        )
        start_button.setCursor(Qt.PointingHandCursor)

        # Hover/pressed styles via parent widget stylesheet
        central.setStyleSheet(
            central.styleSheet()
            + """
QPushButton:hover {
    background-color: #1d4ed8;
}
QPushButton:pressed {
    background-color: #1e40af;
}
"""
        )
        start_button.clicked.connect(self.open_app)

        btn_container = QHBoxLayout()
        btn_container.addStretch(1)
        btn_container.addWidget(start_button)
        btn_container.addStretch(1)

        layout.addLayout(btn_container)

    def open_app(self) -> None:
        # Open the main EEG application window and close the home window
        self.app_window = MainWindow()  # type: ignore[name-defined]
        self.app_window.show()
        self.close()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EEG GUI Viewer")
        self.resize(900, 600)

        # Data buffer
        self.buffer: Deque[float] = deque(maxlen=SAMPLES_TO_SHOW)
        self.stop_event: Optional[threading.Event] = None
        self.reader: Optional[SerialReader] = None
        # (label, line2d) for each loaded history CSV
        self.history_entries: List[Tuple[str, Any]] = []

        # ML classifier
        self.model: Any = None
        self.window_samples: int = int(WINDOW_SECONDS * DEFAULT_FS)
        self._load_model_if_available()

        # Y-scale control flags
        self.live_autoscale: bool = True
        self.history_autoscale: bool = True

        # UI
        self._init_ui()

        # Timer for updating plot
        self.timer = QTimer(self)
        self.timer.setInterval(50)  # ms
        self.timer.timeout.connect(self.update_plot)

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        central.setLayout(layout)
        central.setStyleSheet(
            "background-color: #f5f7fb; font-family: 'Arial', sans-serif; font-size: 12px;"
        )

        # Header with left and right logos
        header_layout = QHBoxLayout()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        left_logo_path = os.path.join(base_dir, "images", "faculty_logo.jpeg")
        right_logo_path = os.path.join(base_dir, "images", "department_logo.jpeg")

        self.left_logo_label = QLabel()
        self.right_logo_label = QLabel()

        # Load and scale logos if available
        left_pix = QPixmap(left_logo_path)
        if not left_pix.isNull():
            self.left_logo_label.setPixmap(
                left_pix.scaledToHeight(90, Qt.SmoothTransformation)
            )

        right_pix = QPixmap(right_logo_path)
        if not right_pix.isNull():
            self.right_logo_label.setPixmap(
                right_pix.scaledToHeight(90, Qt.SmoothTransformation)
            )

        self.left_logo_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.right_logo_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header_layout.setContentsMargins(0, 0, 0, 10)
        header_layout.addWidget(self.left_logo_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.right_logo_label)

        layout.addLayout(header_layout)

        # Main content card (plots + history list)
        content_frame = QFrame()
        content_frame.setFrameShape(QFrame.StyledPanel)
        content_frame.setStyleSheet(
            "QFrame {"
            "  background-color: white;"
            "  border-radius: 10px;"
            "  border: 1px solid #d8e2ef;"
            "}"
        )
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(6)

        # Matplotlib canvas
        self.canvas = MplCanvas(self)
        content_layout.addWidget(self.canvas)

        # Matplotlib navigation toolbar (zoom, pan, save, etc.)
        self.toolbar = NavigationToolbar(self.canvas, self)
        content_layout.addWidget(self.toolbar)

        # List of loaded history signals (each CSV)
        self.history_list = QListWidget()
        self.history_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.history_list.setMinimumHeight(70)
        self.history_list.setStyleSheet(
            "QListWidget {"
            "  border-radius: 6px;"
            "  border: 1px solid #d8e2ef;"
            "  padding: 4px;"
            "}"
        )
        content_layout.addWidget(self.history_list)

        layout.addWidget(content_frame)

        self.x = np.arange(SAMPLES_TO_SHOW)
        self.y = np.zeros(SAMPLES_TO_SHOW)
        (self.line_live,) = self.canvas.ax_live.plot(
            self.x, self.y, label="Live Voltage", lw=1.0
        )

        # Configure live axis
        self.canvas.ax_live.set_xlabel("Sample")
        self.canvas.ax_live.set_ylabel("Voltage (V)")
        self.canvas.ax_live.set_title("Current Run (Live)")
        self.canvas.ax_live.grid(True)
        self.canvas.ax_live.set_ylim(-1.0, 1.0)
        self.canvas.ax_live.legend(loc="upper right")

        # Configure history axis
        self.canvas.ax_history.set_xlabel("Sample")
        self.canvas.ax_history.set_ylabel("Voltage (V)")
        self.canvas.ax_history.set_title("History Runs (Loaded CSVs)")
        self.canvas.ax_history.grid(True)
        # Default X scale for history: 0, 100, 200
        self.canvas.ax_history.set_xlim(0, 200)
        self.canvas.ax_history.set_xticks([0, 100, 200])

        # Controls row
        controls = QHBoxLayout()
        controls.setSpacing(8)

        def style_button(btn: QPushButton, primary: bool = False) -> None:
            if primary:
                btn.setStyleSheet(
                    "QPushButton {"
                    "  background-color: #2563eb;"
                    "  color: white;"
                    "  border-radius: 4px;"
                    "  padding: 6px 12px;"
                    "  font-weight: 600;"
                    "  border: none;"
                    "}"
                    "QPushButton:hover { background-color: #1d4ed8; }"
                    "QPushButton:pressed { background-color: #1e40af; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton {"
                    "  background-color: #e5edff;"
                    "  color: #1f2933;"
                    "  border-radius: 4px;"
                    "  padding: 6px 10px;"
                    "  border: 1px solid #cbd2d9;"
                    "}"
                    "QPushButton:hover { background-color: #d4e2ff; }"
                    "QPushButton:pressed { background-color: #c1d1ff; }"
                )
            btn.setCursor(Qt.PointingHandCursor)

        self.btn_start = QPushButton("Start")
        style_button(self.btn_start, primary=True)
        self.btn_start.clicked.connect(self.start_acquisition)
        controls.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop")
        style_button(self.btn_stop)
        self.btn_stop.clicked.connect(self.stop_acquisition)
        self.btn_stop.setEnabled(False)
        controls.addWidget(self.btn_stop)

        self.btn_load = QPushButton("Load History CSV")
        style_button(self.btn_load)
        self.btn_load.clicked.connect(self.load_history)
        controls.addWidget(self.btn_load)

        self.btn_remove_history = QPushButton("Remove Selected History")
        style_button(self.btn_remove_history)
        self.btn_remove_history.clicked.connect(self.remove_selected_history)
        controls.addWidget(self.btn_remove_history)

        # Auto-scale checkboxes for both graphs
        self.chk_live_autoscale = QCheckBox("Live auto scale")
        self.chk_live_autoscale.setChecked(True)
        self.chk_live_autoscale.stateChanged.connect(
            lambda state: setattr(self, "live_autoscale", bool(state))
        )
        self.chk_live_autoscale.setStyleSheet("color: #52606d;")
        controls.addWidget(self.chk_live_autoscale)

        self.chk_history_autoscale = QCheckBox("History auto scale")
        self.chk_history_autoscale.setChecked(True)
        self.chk_history_autoscale.stateChanged.connect(
            lambda state: setattr(self, "history_autoscale", bool(state))
        )
        self.chk_history_autoscale.setStyleSheet("color: #52606d;")
        controls.addWidget(self.chk_history_autoscale)

        controls.addStretch(1)

        # Status + mental-state labels grouped on the right
        status_box = QVBoxLayout()
        status_box.setSpacing(2)

        self.status_label = QLabel("Idle")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setStyleSheet("color: #52606d;")

        self.pred_label = QLabel("State: N/A")
        self.pred_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.pred_label.setStyleSheet(
            "font-weight: 600; color: #111827;"
        )

        status_box.addWidget(self.status_label)
        status_box.addWidget(self.pred_label)

        controls.addLayout(status_box)

        layout.addLayout(controls)

    def _load_model_if_available(self) -> None:
        """Load trained EEG mental-state model if the file exists."""
        if os.path.exists(MODEL_PATH):
            try:
                self.model = joblib.load(MODEL_PATH)
                print(f"[INFO] Loaded ML model from {MODEL_PATH}")
                if hasattr(self, "status_label"):
                    self.status_label.setText("Model loaded")
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] Could not load model {MODEL_PATH}: {exc}", file=sys.stderr)
                self.model = None
        else:
            print(f"[INFO] No model found at {MODEL_PATH}. Run train_classifier.py to create one.")

    def start_acquisition(self) -> None:
        if self.reader is not None:
            return

        os.makedirs(DATA_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(DATA_DIR, f"eeg_{ts}.csv")

        self.stop_event = threading.Event()
        self.reader = SerialReader(
            port=SERIAL_PORT,
            baud_rate=BAUD_RATE,
            buffer=self.buffer,
            stop_event=self.stop_event,
            csv_path=csv_path,
        )
        self.reader.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText(f"Recording... {csv_path}")

        self.timer.start()

    def stop_acquisition(self) -> None:
        if self.reader is None or self.stop_event is None:
            return

        self.stop_event.set()
        self.reader.join(timeout=2.0)
        self.reader = None
        self.stop_event = None

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Stopped")

        self.timer.stop()

    def update_plot(self) -> None:
        if self.buffer:
            data = np.array(list(self.buffer), dtype=float)

            if data.size < SAMPLES_TO_SHOW:
                if data.size == 0:
                    padded = np.zeros(SAMPLES_TO_SHOW)
                else:
                    pad_value = data[0]
                    pad_len = SAMPLES_TO_SHOW - data.size
                    padded = np.concatenate(
                        [np.full(pad_len, pad_value, dtype=float), data]
                    )
            else:
                padded = data[-SAMPLES_TO_SHOW:]

            self.line_live.set_ydata(padded)

            y_min, y_max = padded.min(), padded.max()
            if y_min == y_max:
                y_min -= 1.0
                y_max += 1.0
            margin = 0.1 * (y_max - y_min)
            # Only auto-adjust Y limits if enabled; otherwise, keep user's zoom
            if self.live_autoscale:
                self.canvas.ax_live.set_ylim(y_min - margin, y_max + margin)

            # Classify mental state based on current voltage window
            if padded.size >= self.window_samples:
                window = padded[-self.window_samples :]
                window_arr = np.asarray(window, dtype=float)
                mean_v = float(np.mean(window_arr))
                peak_v = float(np.max(window_arr))
                frac_above_17 = float(np.mean(window_arr > 1.7))
                frac_above_19 = float(np.mean(window_arr > 1.9))

                # Debug: print 5-second statistics to console
                print(
                    f"[DEBUG] 5s mean={mean_v:.4f}, peak={peak_v:.4f}, "
                    f"frac>1.7={frac_above_17:.3f}, frac>1.9={frac_above_19:.3f}"
                )

                # More robust rule-based classification using activity ratio:
                # - Focused: strong activity, frequent peaks above ~1.9 V
                # - Relaxed: noticeable activity above 1.7 V, but weaker high peaks
                # - Sleepy: almost no time spent above 1.7 V
                if frac_above_19 >= 0.15 or (peak_v >= 2.0 and frac_above_19 >= 0.05):
                    name = "Focused"
                    color = CLASS_COLORS.get(1, "blue")
                elif frac_above_17 >= 0.10:
                    name = "Relaxed"
                    color = CLASS_COLORS.get(0, "green")
                else:
                    name = "Sleepy"
                    color = CLASS_COLORS.get(2, "orange")

                self.pred_label.setText(f"State: {name}")
                self.pred_label.setStyleSheet(f"color: {color}; font-weight: bold;")

            self.canvas.draw_idle()

    def _rebuild_history_list(self) -> None:
        """Refresh the list widget showing loaded history signals."""
        self.history_list.clear()
        for label, _ in self.history_entries:
            self.history_list.addItem(label)

    def remove_selected_history(self) -> None:
        """Remove selected history signals from the bottom graph."""
        if not self.history_entries:
            return

        selected_rows = sorted(
            {index.row() for index in self.history_list.selectedIndexes()},
            reverse=True,
        )
        if not selected_rows:
            return

        for row in selected_rows:
            if 0 <= row < len(self.history_entries):
                _label, line = self.history_entries.pop(row)
                try:
                    line.remove()
                except ValueError:
                    # Line already removed or invalid
                    continue

        self._rebuild_history_list()
        if self.history_entries:
            self.canvas.ax_history.legend(loc="upper right")
            self.canvas.ax_history.relim()
            self.canvas.ax_history.autoscale_view()
        else:
            self.canvas.ax_history.cla()
            self.canvas.ax_history.set_xlabel("Sample")
            self.canvas.ax_history.set_ylabel("Voltage (V)")
            self.canvas.ax_history.set_title("History Runs (Loaded CSVs)")
            self.canvas.ax_history.grid(True)

        self.canvas.draw_idle()

    def load_history(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open EEG CSV",
            DATA_DIR,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        times: List[float] = []
        voltages: List[float] = []
        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    v_str = row.get("voltage")
                    if not v_str:
                        continue
                    try:
                        v = float(v_str)
                    except ValueError:
                        continue
                    voltages.append(v)
                    times.append(len(times))  # simple sample index
        except OSError as exc:
            print(f"[ERROR] Could not read history file {path}: {exc}", file=sys.stderr)
            return

        if not voltages:
            return

        times_arr = np.array(times, dtype=float)
        volts_arr = np.array(voltages, dtype=float)

        # Plot this CSV as its own history run in the bottom axis
        (line_hist,) = self.canvas.ax_history.plot(
            times_arr,
            volts_arr,
            label=os.path.basename(path),
            linestyle="--",
        )
        self.history_entries.append((os.path.basename(path), line_hist))
        self._rebuild_history_list()

        # Only auto-scale history axis (Y only) if enabled.
        # X scale remains independent from live and defaults to 0–200 unless user zooms.
        self.canvas.ax_history.legend(loc="upper right")
        if self.history_autoscale:
            self.canvas.ax_history.relim()
            self.canvas.ax_history.autoscale_view(scalex=False, scaley=True)
        self.canvas.draw_idle()

        self.status_label.setText(f"Loaded history: {os.path.basename(path)}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.stop_acquisition()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    home = HomeWindow()
    home.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


