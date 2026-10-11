"""Offline tests: the orchestrator runs against mock decider/LLM servers, so no models are needed.
Run:  python3 tests/test_tinker.py      (standard library only)"""
import copy, json, os, re, shutil, sys, tempfile, threading, unittest, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
TMP = tempfile.mkdtemp(prefix="tinker-test-")                  # trace.jsonl and out/ files go here, not into your project
os.makedirs(os.path.join(TMP, "config"))
shutil.copy(os.path.join(ROOT, "config", "skills.json"), os.path.join(TMP, "config"))
os.environ["TINKER_HOME"] = TMP
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))
import settings, routing, tinker                               # noqa: E402

LLM_CALLS = []


def read(path):
    with open(path) as f:
        return f.read()


class Quiet(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers["Content-Length"])))


class MockDecider(Quiet):
    def do_POST(self):
        req = self.body(); text = req["text"].lower(); out = []
        for q in req["questions"]:
            if q["question"] == routing.Q_MULTI:
                out.append({"choice": "yes" if " then " in text else "no", "confidence": 0.9})
                continue
            want = ("code" if re.search(r"python|bash|script|function", text) else
                    "reason" if re.search(r"times|plus|solve", text) else
                    "write" if re.search(r"email|poem|haiku|letter", text) else "chat")
            pick = next(o for o in q["options"] if o.startswith({"code": "write, fix", "reason": "math", "write": "draft", "chat": "casual"}[want]))
            out.append({"choice": pick, "confidence": 0.9})
        self.reply(out)


class MockLLM(Quiet):
    def do_POST(self):
        req = self.body(); LLM_CALLS.append(req)
        if req.get("response_format"):                      # the planner
            parts = [p.strip() for p in re.split(r"\bthen\b", req["messages"][-1]["content"]) if p.strip()]
            parts = [re.sub(r"^first\s+", "", p) for p in parts]
            content = json.dumps({"steps": parts})
        else:
            content = f"[{req['model']}] ok"
        self.reply({"choices": [{"message": {"content": content}}]})


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsrv, cls.durl = serve(MockDecider)
        cls.lsrv, cls.lurl = serve(MockLLM)

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.dsrv, cls.lsrv):
            srv.shutdown(); srv.server_close()

    def setUp(self):
        LLM_CALLS.clear()
        self.cfg = settings.load()
        self.cfg["decider_url"], self.cfg["llm_url"] = self.durl, self.lurl
        self.said = []

    def run_handle(self, text):
        return tinker.handle(text, self.said.append, self.cfg)


class TestConfig(unittest.TestCase):
    def cfg(self):
        return json.loads(read(os.path.join(ROOT, "config", "skills.json")))

    def load_from(self, cfg):
        p = os.path.join(TMP, "bad.json")
        with open(p, "w") as f:
            json.dump(cfg, f)
        return settings.load(p)

    def test_default_config_is_valid(self):
        c = settings.load()
        self.assertEqual([n for n, _ in routing.routable(c)], ["chat", "code", "reason", "write"])
        self.assertNotIn("deep", [n for n, _ in routing.routable(c)])     # opt-in only

    def test_missing_field(self):
        c = self.cfg(); del c["skills"]["chat"]["system"]
        with self.assertRaisesRegex(settings.ConfigError, "chat.*system"):
            self.load_from(c)

    def test_bad_output_mode(self):
        c = self.cfg(); c["skills"]["chat"]["output"] = "shout"
        with self.assertRaisesRegex(settings.ConfigError, "output"):
            self.load_from(c)

    def test_duplicate_route_description(self):
        c = self.cfg(); c["skills"]["code"]["route_description"] = c["skills"]["chat"]["route_description"]
        with self.assertRaisesRegex(settings.ConfigError, "same route_description"):
            self.load_from(c)

    def test_invalid_json(self):
        p = os.path.join(TMP, "broken.json")
        with open(p, "w") as f:
            f.write("{nope")
        with self.assertRaisesRegex(settings.ConfigError, "not valid JSON"):
            settings.load(p)


class TestRouting(Base):
    def test_picks_each_skill(self):
        for text, want in [("hello there", "chat"), ("write a python function", "code"),
                           ("what is 17 times 23", "reason"), ("write an email to my landlord", "write")]:
            self.assertEqual(routing.route(text, self.cfg)["skill"], want, text)

    def test_multi_question_is_skipped_for_short_requests(self):
        self.assertFalse(routing.maybe_multi("what is the capital of australia", self.cfg))
        self.assertTrue(routing.maybe_multi("write a haiku and then translate it", self.cfg))
        self.assertTrue(routing.maybe_multi(" ".join(["word"] * 12), self.cfg))


class TestHandle(Base):
    def test_chat_is_one_step_no_thinking(self):
        shown, last, out, saved = self.run_handle("hello there")
        self.assertEqual(last, "chat"); self.assertIsNone(saved)
        self.assertIn("[minicpm5]", out)
        call = LLM_CALLS[-1]
        self.assertEqual(call["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(call["messages"][0]["content"], self.cfg["skills"]["chat"]["system"])
        self.assertEqual(call["max_tokens"], 300)

    def test_write_is_saved_to_file_and_traced(self):
        shown, last, out, saved = self.run_handle("write an email to my landlord")
        self.assertEqual(last, "write"); self.assertTrue(os.path.isfile(saved))
        self.assertIn("[gemma4]", read(saved))
        lines = read(os.path.join(TMP, "logs", "trace.jsonl")).strip().splitlines()
        self.assertEqual(json.loads(lines[-1])["text"], "write an email to my landlord")
        self.assertIn("Working on it.", self.said)

    def test_trace_can_be_disabled(self):
        path = os.path.join(TMP, "logs", "trace.jsonl")
        before = len(read(path).splitlines()) if os.path.exists(path) else 0
        self.cfg["trace"] = False
        self.run_handle("hello there")
        after = len(read(path).splitlines()) if os.path.exists(path) else 0
        self.assertEqual(before, after)

    def test_multi_step_plan_runs_in_order_with_context(self):
        shown, last, out, saved = self.run_handle("first write a haiku about rain then translate it to french")
        planner = [c for c in LLM_CALLS if c.get("response_format")]
        self.assertEqual(len(planner), 1)
        steps = [c for c in LLM_CALLS if not c.get("response_format")]
        self.assertEqual(len(steps), 2)
        self.assertIn("write a haiku about rain", steps[0]["messages"][-1]["content"])
        self.assertIn("Results so far", steps[1]["messages"][-1]["content"])      # step 2 sees step 1
        self.assertTrue(steps[0]["messages"][0]["content"].endswith("no commentary."))   # brief mode
        self.assertLessEqual(steps[0]["max_tokens"], 500)
        self.assertEqual(shown.count("["), 4)                                          # 2 headings + 2 "[model]" tags
        self.assertIsNotNone(saved)

    def test_deep_trigger_uses_deep_skill(self):
        shown, last, out, saved = self.run_handle("think hard about what 17 times 23 is")
        self.assertEqual(last, "deep")
        self.assertEqual(LLM_CALLS[-1]["model"], "vibethinker")
        self.assertNotIn("chat_template_kwargs", LLM_CALLS[-1])               # thinking stays on
        self.assertIn("Let me think about that.", self.said)

    def test_deep_is_not_used_for_write(self):
        shown, last, out, saved = self.run_handle("think hard and write an email to my landlord")
        self.assertEqual(last, "write")

    def test_env_model_override(self):
        os.environ["TINKER_MODEL_CODE"] = "gemma4"
        try:
            self.run_handle("write a python function")
        finally:
            del os.environ["TINKER_MODEL_CODE"]
        self.assertEqual(LLM_CALLS[-1]["model"], "gemma4")

    def test_extra_sampler_options_are_passed(self):
        self.cfg["skills"]["chat"]["extra"] = {"top_k": 20, "min_p": 0.0}
        self.run_handle("hello there")
        self.assertEqual((LLM_CALLS[-1]["top_k"], LLM_CALLS[-1]["min_p"]), (20, 0.0))

    def test_unreachable_brain_raises_urlerror(self):
        self.cfg["decider_url"] = "http://127.0.0.1:9"
        with self.assertRaises(urllib.error.URLError):
            self.run_handle("hello there")


class TestExplain(unittest.TestCase):
    def test_http_error_points_at_the_model_config(self):
        err = urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
        self.assertIn("missing from config/models.ini", tinker.explain(err))

    def test_connection_error_says_start_the_stack(self):
        self.assertIn("tinker up", tinker.explain(urllib.error.URLError("refused")))


class TestSpoken(unittest.TestCase):
    def setUp(self):
        self.cfg = settings.load()["skills"]

    def test_answer_line_only(self):
        out = "17 multiplied by 23 equals 391.\nAnswer: 391"
        self.assertEqual(tinker.spoken(self.cfg["reason"], out), "391")

    def test_falls_back_to_last_line(self):
        self.assertEqual(tinker.spoken(self.cfg["reason"], "step one\nthe result is 51"), "the result is 51")

    def test_markdown_and_latex_are_cleaned(self):
        self.assertEqual(tinker.spoken(self.cfg["chat"], "**Hello** `there` \\boxed{5}"), "Hello there 5")

    def test_strip_thinking(self):
        self.assertEqual(tinker.strip_thinking("<think>hmm</think>The answer"), "The answer")
        self.assertIn("ran out of room", tinker.strip_thinking("<think>never closed"))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
