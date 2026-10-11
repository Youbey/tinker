"""Locate the Tinker home folder and load/validate config/skills.json. Standard library only."""
import json, os

HERE = os.path.dirname(os.path.realpath(__file__))
HOME = os.path.realpath(os.environ.get("TINKER_HOME") or os.path.join(HERE, ".."))
SKILLS_PATH = os.environ.get("TINKER_SKILLS") or os.path.join(HOME, "config", "skills.json")

REQUIRED = ("model", "temperature", "top_p", "max_tokens", "thinking", "output", "system")
OUTPUTS = ("speak", "answer_line", "file")   # spoken in full | only the 'Answer:' line | printed + saved to out/
DEFAULTS = {
    "llm_url": "http://127.0.0.1:8080",
    "decider_url": "http://127.0.0.1:8081",
    "confidence_min": 0.55,
    "fallback_skill": "chat",
    "trace": True,
    "multi_step": {"planner_model": "minicpm5", "min_words": 12, "max_steps": 4,
                   "trigger_words": ["then", "after that", "afterwards", "first", "next", "finally", "and also"]},
    "deep": {"skill": "deep", "trigger": r"\b(think (really )?hard|think deeply|deep think)\b", "not_for": []},
}


class ConfigError(Exception):
    pass


def load(path=None):
    path = path or SKILLS_PATH
    try:
        with open(path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"missing {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}")

    for key, default in DEFAULTS.items():
        if isinstance(default, dict):
            cfg[key] = {**default, **cfg.get(key, {})}
        else:
            cfg.setdefault(key, default)
    # environment wins over the file (handy for tests and experiments)
    cfg["llm_url"] = os.environ.get("TINKER_LLM") or cfg["llm_url"]
    cfg["decider_url"] = os.environ.get("TINKER_DECIDER") or cfg["decider_url"]

    skills = cfg.get("skills") or {}
    if not skills:
        raise ConfigError("'skills' is empty")
    descriptions = []
    for name, s in skills.items():
        missing = [k for k in REQUIRED if k not in s]
        if missing:
            raise ConfigError(f"skill '{name}' is missing: {', '.join(missing)}")
        if s["output"] not in OUTPUTS:
            raise ConfigError(f"skill '{name}': output must be one of {OUTPUTS}, got {s['output']!r}")
        if s.get("route_description"):
            descriptions.append(s["route_description"])
    if len(descriptions) < 2:
        raise ConfigError("need at least two skills with a route_description")
    if len(set(descriptions)) != len(descriptions):
        raise ConfigError("two skills share the same route_description (the decider could not tell them apart)")
    if cfg["fallback_skill"] not in skills:
        raise ConfigError(f"fallback_skill {cfg['fallback_skill']!r} is not a skill")
    return cfg
