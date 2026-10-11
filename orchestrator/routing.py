"""System 1 routing via the Decider container. Standard library only."""
import json, re, urllib.request

Q_SKILL = "Which specialist should handle this request?"
Q_MULTI = "Does the request contain several separate tasks that must be done one after another?"


def routable(cfg):
    """[(skill name, description)] for every skill the decider may choose."""
    return [(n, s["route_description"]) for n, s in cfg["skills"].items() if s.get("route_description")]


def maybe_multi(text, cfg):
    """Short requests are almost never multi-step: skip the second (about 1 s) decider question."""
    m = cfg["multi_step"]
    words = "|".join(re.escape(w) for w in m["trigger_words"])
    return len(text.split()) >= m["min_words"] or bool(re.search(rf"\b({words})\b", text, re.I))


def route(text, cfg, allow_multi=True):
    options = routable(cfg)
    questions = [{"question": Q_SKILL, "options": [d for _, d in options]}]
    check_multi = allow_multi and maybe_multi(text, cfg)
    if check_multi:
        questions.append({"question": Q_MULTI, "options": ["no", "yes"]})
    req = urllib.request.Request(cfg["decider_url"] + "/decide",
                                 json.dumps({"text": text, "questions": questions}).encode(),
                                 {"Content-Type": "application/json"})
    answers = json.load(urllib.request.urlopen(req, timeout=30))
    skill = next((n for n, d in options if d == answers[0]["choice"]), None)
    conf = answers[0]["confidence"] if skill else 0.0      # unknown answer -> caller falls back
    multi, multi_conf = False, 1.0
    if check_multi:
        multi, multi_conf = answers[1]["choice"] == "yes", answers[1]["confidence"]
    return {"skill": skill or cfg["fallback_skill"], "skill_conf": conf, "multi": multi, "multi_conf": multi_conf}
