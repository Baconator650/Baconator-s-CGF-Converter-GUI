"""Windowed entry point. The application has one canonical implementation."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().with_name("SC_CGF_Converter.py")), run_name="__main__")
