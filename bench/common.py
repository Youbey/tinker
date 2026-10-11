"""Shared helpers for the Tinker benchmarks. Standard library only (numpy only where audio is used)."""
import json, os, re, sys, time, urllib.request

BENCH = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.realpath(os.path.join(BENCH, ".."))
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))
import settings                                           # noqa: E402  (finds TINKER_HOME and loads skills.json)

HOME = settings.HOME


def cfg():
    return settings.load()


def data(name):
    """Load a JSON test file that lives next to the benchmarks."""
    with open(os.path.join(BENCH, name)) as f:
        return json.load(f)


def post(url, body, timeout=900):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def chat(url, model, messages, max_tokens=200, temperature=1.0, top_p=0.95, think=None, extra=None):
    """One chat completion. think=False switches reasoning off (MiniCPM5/Qwen-style chat templates)."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "top_p": top_p}
    if think is False:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    body.update(extra or {})
    t0 = time.time()
    r = post(url.rstrip("/") + "/v1/chat/completions", body)
    m, ch = r["choices"][0]["message"], r["choices"][0]
    text = m.get("content") or ""
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return {"text": text.strip(), "reasoning": m.get("reasoning_content") or "", "finish": ch.get("finish_reason"),
            "tokens": r.get("usage", {}).get("completion_tokens", 0), "timings": r.get("timings", {}),
            "wall": time.time() - t0}


# ---- scoring text: "seventeen times twenty three", "17 times 23" and "17x23" must compare equal ----
NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
       "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
       "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def words(text):
    t = text.lower().replace("-", " ")
    t = re.sub(r"(\d)\s*x\s*(\d)", r"\1 times \2", t)
    t = re.sub(r"(\d)[.:](\d)", r"\1 \2", t)
    toks = re.sub(r"[^a-z0-9 ]", " ", t).split()
    out, i = [], 0
    while i < len(toks):
        w = toks[i]
        if w in TENS:
            v = TENS[w]
            if i + 1 < len(toks) and toks[i + 1] in NUM and 1 <= NUM[toks[i + 1]] <= 9:
                v += NUM[toks[i + 1]]; i += 1
            out.append(str(v))
        elif w in NUM:
            out.append(str(NUM[w]))
        else:
            out.append(w)
        i += 1
    return out


def edit_distance(ref, hyp):
    """Word-level Levenshtein distance between two strings; returns (errors, reference word count)."""
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)], len(r)
