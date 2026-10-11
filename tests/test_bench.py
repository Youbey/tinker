"""Offline tests for bench/: scoring helpers, the code sandbox runner, and the scripts run against a mock LLM.
Run:  python3 tests/test_bench.py      (stoplight: numpy is only needed for the audio helper tests)"""
import json, os, re, shutil, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
TMP = tempfile.mkdtemp(prefix="tinker-bench-test-")
os.makedirs(os.path.join(TMP, "config"))
shutil.copy(os.path.join(ROOT, "config", "skills.json"), os.path.join(TMP, "config"))
os.environ["TINKER_HOME"] = TMP
sys.path.insert(0, os.path.join(ROOT, "bench"))
import common, code_bench                                    # noqa: E402

try:
    import numpy as np
    import stt_bench
except ImportError:
    np = stt_bench = None

GOOD = {"reverse_words": "def reverse_words(s):\n    return ' '.join(s.split()[::-1])"}
CALLS = []


class MockLLM(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); CALLS.append(req)
        prompt = req["messages"][-1]["content"]
        if "reverse_words" in prompt:
            content = f"```python\n{GOOD['reverse_words']}\n```"
        elif "flatten(x)" in prompt:
            content = ("def flatten(x):\n    out = []\n    for i in x:\n        out.extend(flatten(i) if isinstance(i, list) else [i])\n"
                       "    return out")                                      # correct, but with NO code fence
        elif "Python function" in prompt:
            content = "```python\ndef nothing(): pass\n```"             # wrong on purpose
        elif "17 times 23" in prompt:
            content = "The answer is 391."
        else:
            content = "I do not know."
        b = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                        "usage": {"completion_tokens": 7}, "timings": {"predicted_per_second": 20.0}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class TestScoring(unittest.TestCase):
    def test_numbers_compare_equal(self):
        self.assertEqual(common.words("seventeen times twenty three"), common.words("17 times 23"))
        self.assertEqual(common.words("17x23"), common.words("seventeen times twenty three"))
        self.assertEqual(common.words("nine thirty"), common.words("9.30"))
        self.assertEqual(common.words("twenty-three"), ["23"])

    def test_edit_distance(self):
        self.assertEqual(common.edit_distance("write an email", "write an email"), (0, 3))
        self.assertEqual(common.edit_distance("write an email", "I write an email"), (1, 3))       # insertion
        self.assertEqual(common.edit_distance("good morning how are you", "morning how are you"), (1, 5))   # dropped word
        self.assertEqual(common.edit_distance("the heater", "the hater"), (1, 2))                   # substitution

    def test_data_files_are_consistent_with_config(self):
        cfg = common.cfg(); skills = set(cfg["skills"])
        for c in common.data("routing_cases.json"):
            self.assertTrue(c["skill"] is None or c["skill"] in skills, c)
        for t in common.data("code_tasks.json"):
            self.assertTrue({"name", "prompt", "asserts"} <= set(t), t)
            compile(t["asserts"], "<asserts>", "exec")
        for t in common.data("reason_tasks.json"):
            re.compile(t["pattern"])


class TestSandboxRunner(unittest.TestCase):
    def test_extract_code(self):
        self.assertEqual(code_bench.extract_code("x\n```python\nA\n```\ny"), "A\n")
        self.assertIsNone(code_bench.extract_code("no fenced block here"))

    def test_lenient_extraction_separates_format_from_correctness(self):
        self.assertEqual(code_bench.extract_code_lenient("```python\nA\n```"), ("A\n", True))
        code, fenced = code_bench.extract_code_lenient("def f():\n    return 1")
        self.assertEqual((code, fenced), ("def f():\n    return 1", False))
        self.assertEqual(code_bench.extract_code_lenient("sorry, I cannot do that"), (None, False))

    def test_pass_and_fail(self):
        ok, why = code_bench.run_code(GOOD["reverse_words"], "assert reverse_words('a b') == 'b a'", "local")
        self.assertTrue(ok, why)
        ok, why = code_bench.run_code(GOOD["reverse_words"], "assert reverse_words('a b') == 'a b'", "local")
        self.assertFalse(ok); self.assertIn("AssertionError", why)

    def test_timeout(self):
        ok, why = code_bench.run_code("import time\ntime.sleep(5)", "", "local", timeout=1)
        self.assertEqual((ok, why), (False, "timeout"))


@unittest.skipUnless(stt_bench, "numpy not installed")
class TestAudioHelpers(unittest.TestCase):
    def test_trim(self):
        a = np.arange(16000 * 2, dtype=np.float32)
        self.assertEqual(len(stt_bench.trimmed(a, 0.25, 0.25)), 16000 * 2 - 8000)
        self.assertEqual(len(stt_bench.trimmed(a, 0, 0)), len(a))

    def test_sentences_file(self):
        self.assertEqual(len(stt_bench.sentences()), 10)


class TestScriptsAgainstMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.env = dict(os.environ, TINKER_HOME=TMP, TINKER_LLM=f"http://127.0.0.1:{cls.srv.server_address[1]}")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def run_script(self, *args):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "bench", args[0]), *args[1:]],
                           env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_chat_test(self):
        out = self.run_script("chat_test.py", "minicpm5", "What", "is", "17 times 23?", "--no-think")
        self.assertIn("REPLY: The answer is 391.", out); self.assertIn("generate 20.0 tok/s", out)
        self.assertEqual(CALLS[-1]["chat_template_kwargs"], {"enable_thinking": False})

    def test_reason_bench_scores_answers(self):
        out = self.run_script("reason_bench.py", "minicpm5:nothink")
        lines = [l for l in out.splitlines() if "tok |" in l]
        self.assertEqual(len(lines), 3)
        self.assertIn("CORRECT", lines[0]); self.assertIn("WRONG/INCOMPLETE", lines[1])        # only Q1 matches the mock

    def test_code_bench_counts_passes(self):
        out = self.run_script("code_bench.py", "minicpm5:1.0", "-n", "2", "--runner", "local", "--top-k", "20", "--min-p", "0")
        self.assertIn("minicpm5     temp=1.0: 4/10 passed (2 without a code fence)", out)   # reverse_words (fenced) + flatten (bare)
        self.assertIn("FAIL is_palindrome", out)
        self.assertEqual((CALLS[-1]["top_k"], CALLS[-1]["min_p"]), (20, 0.0))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
