#!/usr/bin/env python3
"""Record 4 s from every audio source and print the peak level. Keep talking normally. Aim for 30-80%, no clipping."""
import json, re, subprocess, wave
import numpy as np

dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout)
srcs = [(n["id"], n["info"]["props"].get("node.description", "?")) for n in dump
        if n.get("type") == "PipeWire:Interface:Node" and n["info"]["props"].get("media.class") == "Audio/Source"]
m = re.search(r"id (\d+)", subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SOURCE@"], capture_output=True, text=True).stdout)
default = int(m.group(1)) if m else None
print("Sources found:", len(srcs))
for sid, desc in srcs:
    path = f"/tmp/miccheck-{sid}.wav"
    print(f"\n[{sid}] {desc}{'   <- current default' if sid == default else ''}\n  talk for 4 s ...", flush=True)
    subprocess.run(["timeout", "-s", "INT", "4", "pw-record", "--target", str(sid), "--rate", "16000",
                    "--channels", "1", "--format", "s16", path])
    try:
        with wave.open(path, "rb") as w:
            a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
        print(f"  peak {np.abs(a).max() * 100:.0f}%  clipped samples {(np.abs(a) > 0.98).sum()}")
    except Exception as e:
        print("  could not record:", e)
