"""Test-wide setup."""
import os

# Workers write a diagnostics report; tests must not overwrite the real one.
os.environ.setdefault("RPGM_NO_DIAGNOSTICS", "1")
