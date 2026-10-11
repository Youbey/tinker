#!/usr/bin/env python3
"""Score the decider on bench/routing_cases.json (add your own cases there).  usage: routing_bench.py"""
import time
from common import cfg, data
from routing import route

c = cfg()
ok_skill = n_skill = ok_multi = 0
cases = data("routing_cases.json")
for case in cases:
    t = time.time(); r = route(case["text"], c); ms = (time.time() - t) * 1000
    s_ok = case["skill"] is None or r["skill"] == case["skill"]
    m_ok = r["multi"] == case["multi"]
    n_skill += case["skill"] is not None; ok_skill += case["skill"] is not None and s_ok; ok_multi += m_ok
    print(f"{'OK ' if s_ok and m_ok else 'BAD'} {ms:5.0f}ms  {r['skill']:6s} {r['skill_conf']:.2f} | "
          f"multi={r['multi']!s:5} {r['multi_conf']:.2f} | {case['text'][:60]}")
print(f"\nskill: {ok_skill}/{n_skill}   multi-step flag: {ok_multi}/{len(cases)}")
