"""After copying the my.telegram.org page, shows whether تجميعة can find the key in it.
Never prints the key: every run of 4+ digits/hex letters is hidden.
Usage: ~/Tajmeea/.venv/bin/python3 ~/Tajmeea/scripts/check-clipboard-key.py
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from tajmeea_engine.errors import UserError  # noqa: E402
from tajmeea_engine.parsing import parse_api_key  # noqa: E402

text = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
try:
    parse_api_key(text)
    print("✓ تجميعة تلقى المفتاح بهالنص.")
except UserError as error:
    print("✗ " + str(error))
print(f"\nطول النص: {len(text)} حرف. شكله والأرقام مخفية:\n")
print(re.sub(r"[0-9a-fA-F]{4,}", "•••", text)[:2000])
