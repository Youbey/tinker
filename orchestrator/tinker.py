#!/usr/bin/env python3
"""Tinker: input -> System 1 route (Decider) -> optional System 2 plan -> specialist model(s) -> output."""
import argparse, datetime, importlib, json, os, re, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import settings
from routing import route

NOTHINK = {"enable_thinking": False}
FACES = {"idle": "( ^ _ ^ )", "listening": "( o _ o )", "thinking": "( - _ - ) ...", "speaking": "( ^ o ^ ) ~"}
BRIEF = " This is one step of a larger job: do only this task, be concise, no options, no commentary."
PLAN_PROMPT = ('Split the request into the FEWEST ordered tasks (2 to 4) that cover it, in the order they must be done. '
               'Never add tasks the user did not ask for. Each task is a short imperative sentence that makes sense on its own. '
               'Reply with JSON only: {"steps":["first task","second task"]} '
               'Keep the original wording of each task. '
               'Example request: write a bash script that backs up my documents folder and then explain each line. '
               'Example reply: {"steps":["Write a bash script that backs up the documents folder","Explain each line of that script"]}')


def face(state):
    print(FACES[state], flush=True)


def post(url, body, timeout=900):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def strip_thinking(t):
    if "</think>" in t:
        return t.split("</think>", 1)[1].strip()
    if t.startswith("<think>"):
        return "I ran out of room while thinking, so I do not have a reliable answer."
    return t


def speakable(t):
    t = re.sub(r"\\boxed\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\\[|\\\]|\\\(|\\\)|\$", "", t)
    t = re.sub(r"[*_`#]+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def spoken(skill_cfg, out):
    """What Tinker says aloud for a finished answer."""
    if skill_cfg["output"] == "answer_line":
        found = re.findall(r"(?im)^\s*answer:\s*(.+)$", out)
        if found:
            out = found[-1]
        else:
            lines = [l for l in out.strip().split("\n") if l.strip()]
            out = lines[-1] if lines else out
    return speakable(out)[:600]


def model_for(skill, s, brief):
    override = os.environ.get(f"TINKER_MODEL_{skill.upper()}")      # e.g. TINKER_MODEL_CODE=gemma4 for an experiment
    if override:
        return override
    if brief and s.get("brief_model"):
        return s["brief_model"]
    return s["model"]


def ask(cfg, skill, task, context="", brief=False):
    s = cfg["skills"][skill]
    user = task if not context else f"{task}\n\nResults so far:\n{context}"
    body = {"model": model_for(skill, s, brief),
            "max_tokens": min(s["max_tokens"], 500) if brief else s["max_tokens"],
            "temperature": s["temperature"], "top_p": s["top_p"],
            "messages": [{"role": "system", "content": s["system"] + (BRIEF if brief else "")},
                         {"role": "user", "content": user}]}
    if not s["thinking"]:
        body["chat_template_kwargs"] = NOTHINK
    body.update(s.get("extra", {}))                                 # optional per-skill sampler extras (top_k, min_p, ...)
    r = post(f"{cfg['llm_url']}/v1/chat/completions", body)
    return strip_thinking((r["choices"][0]["message"].get("content") or "").strip())


def make_plan(text, cfg):
    """System 2 planner. Returns [{skill, task}, ...] or None (the caller then runs one step)."""
    m, raw = cfg["multi_step"], ""
    try:
        r = post(f"{cfg['llm_url']}/v1/chat/completions", {
            "model": m["planner_model"], "max_tokens": 600, "temperature": 0.2,
            "chat_template_kwargs": NOTHINK, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": m.get("planner_system", PLAN_PROMPT)},
                         {"role": "user", "content": text}]}, timeout=180)
        raw = r["choices"][0]["message"].get("content") or ""
        steps = [t["task"] if isinstance(t, dict) else t for t in json.loads(raw)["steps"]]
        if not (1 <= len(steps) <= m["max_steps"] and all(isinstance(t, str) and t.strip() for t in steps)):
            raise ValueError("bad step list")
        return [{"skill": route(t, cfg, allow_multi=False)["skill"], "task": t} for t in steps]   # System 1 picks each specialist
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        raise
    except Exception as e:
        print(f"(planner failed, running as a single step): {e!r} | raw reply: {raw[:300]!r}")
        return None


def handle(text, say, cfg):
    t0 = time.time(); face("thinking")
    skills, conf_min = cfg["skills"], cfg["confidence_min"]
    d = route(text, cfg); t_route = time.time() - t0
    skill = d["skill"] if d["skill_conf"] >= conf_min else cfg["fallback_skill"]
    steps = make_plan(text, cfg) if (d["multi"] and d["multi_conf"] >= conf_min) else None
    if not steps:
        deep = cfg["deep"]
        if deep["skill"] in skills and re.search(deep["trigger"], text, re.I) and skill not in deep["not_for"]:
            skill = deep["skill"]
        steps = [{"skill": skill, "task": text}]
    print(f"route: {d['skill']} ({d['skill_conf']:.2f}) | multi: {d['multi']} ({d['multi_conf']:.2f}) "
          f"| plan: {[s['skill'] for s in steps]} | routing {t_route:.1f}s")

    ctx, parts, announced = "", [], False
    for i, s in enumerate(steps, 1):
        print(f"  step {i}/{len(steps)} [{s['skill']}] {s['task']}", flush=True)
        note = skills[s["skill"]].get("announce")
        if note and not announced:
            say(note); announced = True
        out = ask(cfg, s["skill"], s["task"], ctx, brief=len(steps) > 1)
        ctx += f"\n- {out}"; parts.append((s["task"], out))

    last, last_out = steps[-1]["skill"], parts[-1][1]
    shown = last_out if len(parts) == 1 else "\n\n".join(f"[{t}]\n{o}" for t, o in parts)
    saved = None
    if any(skills[s["skill"]]["output"] == "file" for s in steps):
        outdir = os.path.join(settings.HOME, "out"); os.makedirs(outdir, exist_ok=True)
        saved = os.path.join(outdir, datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".md")
        with open(saved, "w") as f:
            f.write(last_out if len(parts) == 1 else "\n\n".join(f"## {t}\n\n{o}" for t, o in parts))
    if cfg["trace"]:                                                # future training data; kept out of git
        logdir = os.path.join(settings.HOME, "logs"); os.makedirs(logdir, exist_ok=True)
        with open(os.path.join(logdir, "trace.jsonl"), "a") as f:
            f.write(json.dumps({"ts": time.time(), "text": text, "route": d, "plan": steps,
                                "secs": round(time.time() - t0, 1)}) + "\n")
    print(f"total {time.time() - t0:.1f}s")
    return shown, last, last_out, saved


def explain(e):
    """A plain-language message for a failed request to the model server."""
    if isinstance(e, urllib.error.HTTPError):
        return (f"Tinker's brain answered with an error ({e.code} {e.reason}). A model named in config/skills.json "
                "may be missing from config/models.ini.")
    return f"Tinker's brain is not reachable ({e}). Start it with:  tinker up"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", action="store_true", help="use mic and speaker")
    ap.add_argument("--speak", action="store_true", help="type input, hear the answer")
    ap.add_argument("--once", help="handle one request and exit")
    a = ap.parse_args()
    try:
        cfg = settings.load()
    except settings.ConfigError as e:
        sys.exit(f"config error: {e}")
    voice = importlib.import_module("voice") if (a.voice or a.speak) else None
    say = (lambda t: voice.speak(t)) if voice else (lambda t: None)
    print("Tinker is up. Say or type 'goodbye' to stop.")
    while True:
        face("idle")
        if a.once:
            text = a.once
        elif voice and a.voice:
            face("listening"); text = voice.listen()
        else:
            text = input("you> ").strip()
        if not text:
            print("(heard nothing)"); continue
        print("heard:", text)
        if re.sub(r"[^a-z ]", "", text.lower()).strip() in ("goodbye", "good bye", "bye", "bye bye", "exit", "quit", "stop tinker", "shut down"):
            say("Goodbye."); break
        try:
            shown, last, last_out, saved = handle(text, say, cfg)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            print(explain(e))
            if a.once:
                sys.exit(1)
            continue
        print("\ntinker>", shown, "\n")
        face("speaking")
        if saved:
            print(f"(saved to {saved})"); say("Done. I printed it in the terminal and saved it.")
        else:
            say(spoken(cfg["skills"][last], last_out))
        if a.once:
            break


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nbye")
