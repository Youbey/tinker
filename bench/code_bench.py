#!/usr/bin/env python3
"""Does the model's code pass the asserts in bench/code_tasks.json?  Generated code runs in a throwaway
Podman container with NO network (default), so model output never touches your host.
  code_bench.py minicpm5:1.0 gemma4:0.3 [-n 2] [--top-k 20 --min-p 0.0] [--runner podman|local]"""
import argparse, os, re, subprocess, sys, tempfile, time
from common import cfg, chat, data

SYSTEM = "You are a careful Python programmer. Reply with exactly one fenced python code block containing the requested function and nothing else."
IMAGE = "docker.io/library/python:3.12-slim"


def extract_code(reply):
    m = re.search(r"```(?:python)?\n(.*?)```", reply, re.S)
    return m.group(1) if m else None


def extract_code_lenient(reply):
    """(code, fenced). Accepts bare code when the model skipped the fence, so formatting slips and wrong answers stay separate."""
    code = extract_code(reply)
    if code is not None:
        return code, True
    if re.search(r"^\s*(def |class |import |from \w+ import )", reply, re.M):
        return reply, False
    return None, False


def run_code(code, asserts, runner="podman", timeout=60):
    """Returns (passed, reason). The 'local' runner executes model code on THIS machine: for tests only."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.py")
        with open(path, "w") as f:
            f.write(code + "\n\n" + asserts + "\nprint('ok')\n")
        cmd = ([sys.executable, path] if runner == "local" else
               ["podman", "run", "--rm", "--network", "none", "-v", f"{d}:/w:ro,z", IMAGE, "python", "/w/t.py"])
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "timeout"
    ok = p.returncode == 0 and "ok" in p.stdout
    return ok, "" if ok else (p.stderr.strip().splitlines() or ["failed"])[-1][:100]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("configs", nargs="*", default=["minicpm5:1.0"], help="model:temperature")
    ap.add_argument("-n", type=int, default=2, help="samples per task")
    ap.add_argument("--top-k", type=int); ap.add_argument("--min-p", type=float)
    ap.add_argument("--runner", choices=["podman", "local"], default="podman")
    a = ap.parse_args()
    url, tasks = cfg()["llm_url"], data("code_tasks.json")
    extra = {k: v for k, v in (("top_k", a.top_k), ("min_p", a.min_p)) if v is not None}
    for conf in a.configs:
        model, temp = conf.split(":"); ok = tot = unfenced = 0; fails = []; t0 = time.time()
        for task in tasks:
            for _ in range(a.n):
                r = chat(url, model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task["prompt"]}],
                         600, float(temp), think=False, extra=extra)
                code, fenced = extract_code_lenient(r["text"])
                unfenced += code is not None and not fenced
                good, why = (False, "no code in reply") if code is None else run_code(code, task["asserts"], a.runner)
                tot += 1; ok += good
                if not good:
                    fails.append(f"{task['name']}: {why}")
        note = f" ({unfenced} without a code fence)" if unfenced else ""
        print(f"{model:12s} temp={temp}: {ok}/{tot} passed{note} in {time.time() - t0:.0f}s", flush=True)
        for f in fails:
            print("    FAIL", f, flush=True)


if __name__ == "__main__":
    main()
