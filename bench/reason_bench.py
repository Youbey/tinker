#!/usr/bin/env python3
"""Reasoning questions from bench/reason_tasks.json, with the answer checked by a pattern.
  reason_bench.py minicpm5:nothink minicpm5:think vibethinker:think [--max-tokens 4000]"""
import argparse, re
from common import cfg, chat, data

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("configs", nargs="*", default=["minicpm5:nothink"], help="model:think|nothink")
ap.add_argument("--max-tokens", type=int, default=4000)
a = ap.parse_args()
url = cfg()["llm_url"]
for conf in a.configs:
    model, mode = conf.split(":")
    for task in data("reason_tasks.json"):
        r = chat(url, model, [{"role": "user", "content": task["prompt"]}], a.max_tokens,
                 0.9 if (model == "minicpm5" and mode == "think") else 1.0 if mode == "nothink" else 0.6,
                 think=False if mode == "nothink" else None)
        ok = bool(re.search(task["pattern"], r["text"], re.I))
        print(f"{model:11s} {mode:7s} {task['id']} | {r['wall']:6.1f}s | {r['tokens']:5d} tok | finish={r['finish']:6s} | "
              f"{'CORRECT' if ok else 'WRONG/INCOMPLETE'}")
        print("   tail:", repr(r["text"][-150:]), flush=True)
