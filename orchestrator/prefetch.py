#!/usr/bin/env python3
"""Make sure the Whisper base model is on disk. If it already is, make NO network call (a cached load used to
contact the Hugging Face server every time, which was sometimes very slow)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from settings import HOME

os.environ.setdefault("HF_HOME", os.path.join(HOME, "models", "speech", "hf"))
from faster_whisper import WhisperModel

try:
    WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
    print("whisper base: already cached (no network used)")
except Exception:
    WhisperModel("base", device="cpu", compute_type="int8")
    print("whisper base: downloaded")
