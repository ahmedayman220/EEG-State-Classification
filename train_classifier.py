#!/usr/bin/env python3
"""
Train a simple EEG mental state classifier (Relaxed / Focused / Sleepy).

This script is designed to work with an *external* EEG dataset so you can
demonstrate AI integration without depending on your Arduino recordings.

Expected dataset format (CSV):
    - One row per EEG segment (e.g. a few seconds of data)
    - Columns:
        voltage_0, voltage_1, ..., voltage_N-1, label
      where:
        - voltage_* columns contain a fixed-length EEG segment
        - label is an integer {0, 1, 2} or a string
          mapping to: 0=Relaxed, 1=Focused, 2=Sleepy

You can adapt the `load_dataset` function to match the actual format
of whatever EEG dataset you use.

Usage example:
    python train_classifier.py --data path/to/eeg_dataset.csv

The trained model will be saved as:
    models/eeg_state_model.pkl
which is automatically loaded by the GUI (if present).
"""

from __future__ import annotations

import argparse
import os
from typing import Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

from eeg_features import extract_features, DEFAULT_FS


MODEL_DIR = "models"
MODEL_PATH = os.path.join(MODEL_DIR, "eeg_state_model.pkl")

CLASS_MAP_STR_TO_INT = {
    "relaxed": 0,
    "focused": 1,
    "sleepy": 2,
}


def load_dataset(path: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load an external EEG dataset and return (X, y).

    This implementation expects:
        - All columns starting with "voltage_" are raw EEG samples
        - A column named "label" with values in {0,1,2} or {"Relaxed",...}

    Adapt this function if your dataset has a different structure.
    """
    df = pd.read_csv(path)
    if "label" not in df.columns:
        raise ValueError("Dataset must contain a 'label' column.")

    # Select voltage columns (flexible: any column name starting with 'voltage')
    voltage_cols = [c for c in df.columns if c.startswith("voltage_")]
    if not voltage_cols:
        raise ValueError(
            "Dataset must have columns named like 'voltage_0', 'voltage_1', ..."
        )

    X_raw = df[voltage_cols].to_numpy(dtype=float)
    labels = df["label"].to_numpy()

    # Map string labels to ints if needed
    if labels.dtype.kind in {"U", "S", "O"}:
        labels_norm = np.array(
            [CLASS_MAP_STR_TO_INT[str(lbl).strip().lower()] for lbl in labels],
            dtype=int,
        )
    else:
        labels_norm = labels.astype(int)

    # Convert each row (segment) to feature vector
    feats = []
    for row in X_raw:
        feats.append(extract_features(row, fs=DEFAULT_FS))
    X = np.stack(feats, axis=0)

    return X, labels_norm


def train_model(data_path: str) -> None:
    X, y = load_dataset(data_path)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    print("Classification report:")
    print(
        classification_report(
            y_test,
            y_pred,
            target_names=["Relaxed", "Focused", "Sleepy"],
        )
    )

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(clf, MODEL_PATH)
    print(f"Saved trained model to {MODEL_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train EEG mental-state classifier (Relaxed/Focused/Sleepy)."
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to EEG dataset CSV file.",
    )
    args = parser.parse_args()

    train_model(args.data)


if __name__ == "__main__":
    main()


