#!/usr/bin/env python3
"""
Simple real-time EEG viewer for Arduino over serial on macOS.

Expected Arduino output (over serial):
    - One sample per line, e.g. "512" or "0.123"
    - Optionally comma-separated if you have multiple channels,
      this script currently uses only the first numeric value.

Usage:
    1. Create & activate a virtualenv (recommended).
    2. Install dependencies:
           pip install -r requirements.txt
    3. Run:
           python eeg_realtime_plot.py
    4. A window will open showing the live EEG signal.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from collections import deque
from typing import Deque, Optional

import matplotlib.pyplot as plt
import numpy as np
import serial
from matplotlib.animation import FuncAnimation


SERIAL_PORT = "/dev/cu.usbmodem214101"  # macOS Arduino port
BAUD_RATE = 9600                        # Match your Arduino sketch (Serial.begin(9600))
SAMPLES_TO_SHOW = 500                   # Number of samples visible in the window
READ_TIMEOUT = 1.0                      # Seconds


class SerialReader(threading.Thread):
    """
    Background thread that reads samples from the serial port and
    pushes them into a fixed-length buffer.
    """

    def __init__(
        self,
        port: str,
        baud_rate: int,
        buffer: Deque[float],
        stop_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True)
        self._port = port
        self._baud_rate = baud_rate
        self._buffer = buffer
        self._stop_event = stop_event
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

        with self._ser:
            while not self._stop_event.is_set():
                try:
                    line_bytes = self._ser.readline()
                    if not line_bytes:
                        continue

                    line = line_bytes.decode(errors="ignore").strip()
                    if not line:
                        continue

                    value = self._parse_line(line)
                    if value is None:
                        continue

                    self._buffer.append(value)
                except serial.SerialException as exc:
                    print(f"[ERROR] Serial read error: {exc}", file=sys.stderr)
                    break
                except UnicodeDecodeError:
                    # Ignore malformed lines
                    continue

        print("[INFO] SerialReader stopped.")

    @staticmethod
    def _parse_line(line: str) -> Optional[float]:
        """
        Parse a line of text coming from the Arduino.
        Supports:
            "Raw: 1425\tVoltage: 1.87"
            "Raw: 1425 Voltage: 1.87"
            "123"
            "0.123"
            "123,456,789"  -> takes the first value
        """
        # Prefer explicit "Voltage:" field if present
        voltage_match = re.search(r"Voltage:\s*([+-]?\d*\.?\d+)", line, re.IGNORECASE)
        if voltage_match:
            try:
                return float(voltage_match.group(1))
            except ValueError:
                pass

        # Fallback: take first numeric (int/float) token in the line
        number_match = re.search(r"([+-]?\d*\.?\d+)", line)
        if number_match:
            try:
                return float(number_match.group(1))
            except ValueError:
                pass

        # Last resort: original simple comma-based format
        token = line.split(",")[0].strip()
        try:
            return float(token)
        except ValueError:
            return None


def main() -> None:
    buffer: Deque[float] = deque(maxlen=SAMPLES_TO_SHOW)
    stop_event = threading.Event()

    reader = SerialReader(
        port=SERIAL_PORT,
        baud_rate=BAUD_RATE,
        buffer=buffer,
        stop_event=stop_event,
    )
    reader.start()

    # Set up matplotlib figure
    plt.style.use("seaborn-v0_8-darkgrid")
    fig, ax = plt.subplots()
    fig.canvas.manager.set_window_title("EEG Live Viewer")

    x = np.arange(SAMPLES_TO_SHOW)
    y = np.zeros(SAMPLES_TO_SHOW)
    (line,) = ax.plot(x, y, lw=1.0)

    ax.set_xlabel("Sample")
    ax.set_ylabel("Amplitude")
    ax.set_title("EEG Signal (Live)")

    # Set some reasonable initial limits; will auto-scale with data
    ax.set_ylim(-1.0, 1.0)

    def init():
        line.set_ydata(np.zeros_like(x))
        return (line,)

    def update(_frame):
        if buffer:
            data = np.array(list(buffer), dtype=float)

            # If fewer than SAMPLES_TO_SHOW samples, left-pad with last value (or zero)
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

            line.set_ydata(padded)

            # Auto-scale Y axis smoothly
            y_min, y_max = padded.min(), padded.max()
            if y_min == y_max:
                y_min -= 1.0
                y_max += 1.0
            margin = 0.1 * (y_max - y_min)
            ax.set_ylim(y_min - margin, y_max + margin)

        return (line,)

    ani = FuncAnimation(
        fig,
        update,
        init_func=init,
        interval=50,  # ms
        blit=True,
        cache_frame_data=False,  # avoid unbounded cache warning
    )

    try:
        plt.show()
    finally:
        # When the window is closed, stop the serial reader
        stop_event.set()
        reader.join(timeout=2.0)
        print("[INFO] Application exited.")


if __name__ == "__main__":
    main()



