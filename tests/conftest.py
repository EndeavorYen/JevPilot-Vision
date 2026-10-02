"""Test-wide settings."""

import os

# Unit tests never load the perception detector's weights (#18); tests that need perception
# substitute a fake through monkeypatch. Set SEMIF_PERCEPTION=1 to run with the real detector.
os.environ.setdefault("SEMIF_PERCEPTION", "0")
