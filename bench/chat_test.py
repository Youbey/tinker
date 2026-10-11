#!/usr/bin/env python3
"""Ask one model one question and print the reply plus tokens/second.
  chat_test.py minicpm5 "Explain what a mutex is." [--no-think] [--temp 0.7] [--max-tokens 300] [--system "..."]"""
import argparse
from common import cfg, chat

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("model"); ap.add_argument("prompt", nargs="+")
ap.add_argument("--no-think", action="store_true"); ap.add_argument("--temp", type=float, default=1.0)
ap.add_argument("--top-p", type=float, default=0.95); ap.add_argument("--max-tokens", type=int, default=200)
ap.add_argument("--system"); ap.add_argument("--url")
a = ap.parse_args()
msgs = ([{"role": "system", "content": a.system}] if a.system else []) + [{"role": "user", "content": " ".join(a.prompt)}]
r = chat(a.url or cfg()["llm_url"], a.model, msgs, a.max_tokens, a.temp, a.top_p, think=False if a.no_think else None)
print("REPLY:", r["text"])
if r["reasoning"]:
    print("THINKING (first 200 chars):", r["reasoning"][:200].replace("\n", " "))
t = r["timings"]
print(f"wall {r['wall']:.1f}s | prompt {t.get('prompt_per_second', 0):.1f} tok/s | generate {t.get('predicted_per_second', 0):.1f} tok/s | finish={r['finish']}")
