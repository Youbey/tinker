"""Offline tests for install.sh and bin/tinker. Real shell scripts run against STUB podman/hf/curl commands in a restricted
PATH, inside a temp copy of the project: no containers, no network, no GPU. Run:  python3 tests/test_install.py"""
import json, os, shutil, stat, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
REAL_TOOLS = ("bash sh python3 df awk nproc ls cat grep head tail ln mkdir cp mv rm basename dirname readlink tr sed cmp "
              "sort cut tee uname wc id chmod touch date sleep seq env test kill xargs").split()

PODMAN = """#!/bin/sh
echo "podman $*" >> "$STUB_LOG"
case "$*" in
  *"info --format"*) echo true ;;
  *"--version"*) echo "podman version 5.8.7" ;;
  *"--list-devices"*) if [ "${STUB_VULKAN:-1}" = 1 ]; then echo "Vulkan0: Fake GPU (1 MiB)"; else echo "no devices"; fi ;;
esac
exit 0
"""
HF = """#!/bin/sh
echo "hf $*" >> "$STUB_LOG"
[ "${STUB_HF_FAIL:-0}" = 1 ] && { echo "network error" >&2; exit 1; }
dir=""; prev=""
for a in "$@"; do [ "$prev" = "--local-dir" ] && dir="$a"; prev="$a"; done
mkdir -p "$dir"
case "$*" in
  *openbmb*)      echo x > "$dir/MiniCPM5-2B-Q4_K_M.gguf" ;;
  *unsloth*)      echo x > "$dir/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf" ;;
  *Mapika*)       echo x > "$dir/decider-2b-v11-Q8_0.gguf"; echo '{}' > "$dir/decider_config.json" ;;
  *mradermacher*) echo x > "$dir/VibeThinker-3B.Q4_K_M.gguf" ;;
esac
exit 0
"""
FAKE_VELA = """#!/bin/sh
echo "tinker $*" >> "$STUB_LOG"
exit 0
"""


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tinker-install-test-")
        self.proj = os.path.join(self.tmp, "proj")
        shutil.copytree(ROOT, self.proj, symlinks=True, ignore=shutil.ignore_patterns(
            "__pycache__", ".venv", "models", "state", "logs", "out", "voices", ".git", "*.bak", "models.ini", "tinker.env"))   # hermetic: never inherit the real install's generated config
        self.home = os.path.join(self.tmp, "home"); os.makedirs(self.home)
        self.log = os.path.join(self.tmp, "stub.log"); open(self.log, "w").close()
        self.tools = os.path.join(self.tmp, "tools"); os.makedirs(self.tools)
        for t in REAL_TOOLS:
            real = shutil.which(t)
            if real:
                os.symlink(real, os.path.join(self.tools, t))
        write_exec(os.path.join(self.tools, "podman"), PODMAN)
        for t in ("curl", "jq", "pw-record", "pw-play"):
            write_exec(os.path.join(self.tools, t), "#!/bin/sh\nexit 0\n")
        self.hf = os.path.join(self.tmp, "hf"); write_exec(self.hf, HF)
        self.fake_vela = os.path.join(self.tmp, "fake-tinker"); write_exec(self.fake_vela, FAKE_VELA)
        self.reqs = os.path.join(self.tmp, "empty-requirements.txt")
        with open(self.reqs, "w") as f:
            f.write("# nothing to install in tests\n")
        self.dri = os.path.join(self.tmp, "renderD128"); open(self.dri, "w").close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **extra):
        e = {"PATH": self.tools, "HOME": self.home, "SHELL": "/bin/bash", "STUB_LOG": self.log, "TINKER_HF_BIN": self.hf,
             "TINKER_BIN": self.fake_vela, "TINKER_MIN_GB": "1", "TINKER_DRI_GLOB": self.dri, "TINKER_REQUIREMENTS": self.reqs,
             "XDG_RUNTIME_DIR": self.tmp}
        e.update(extra)
        return e

    def install(self, *args, **extra):
        return subprocess.run(["bash", os.path.join(self.proj, "install.sh"), *args], env=self.env(**extra),
                              capture_output=True, text=True, timeout=300)

    def stub_log(self):
        with open(self.log) as f:
            return f.read()

    def read(self, rel):
        with open(os.path.join(self.proj, rel)) as f:
            return f.read()


class TestInstallPlan(Base):
    def test_help(self):
        p = self.install("--help")
        self.assertEqual(p.returncode, 0); self.assertIn("--dry-run", p.stdout); self.assertIn("--uninstall", p.stdout)

    def test_unknown_option(self):
        p = self.install("--bogus")
        self.assertNotEqual(p.returncode, 0); self.assertIn("unknown option", p.stderr)

    def test_dry_run_prints_plan_and_changes_nothing(self):
        p = self.install("--dry-run", "--cpu")
        self.assertEqual(p.returncode, 0, p.stderr)
        for expect in ("podman pull ghcr.io/ggml-org/llama.cpp:server\n", "download openbmb/MiniCPM5-2B-GGUF",
                       "download unsloth/gemma-4-E4B-it-qat-GGUF", "download Mapika/decider-2b-GGUF",
                       "podman build -t localhost/tinker-decider", "[minicpm5]", "[gemma4]", "PROFILE=cpu",
                       "orchestrator/prefetch.py", "piper.download_voices", "nothing was changed"):
            self.assertIn(expect, p.stdout)
        self.assertNotIn("server-vulkan", p.stdout); self.assertNotIn("vibethinker", p.stdout)
        for rel in (".venv", "models", "config/tinker.env", "config/models.ini"):
            self.assertFalse(os.path.exists(os.path.join(self.proj, rel)), rel)
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".local", "bin", "tinker")))

    def test_dry_run_vulkan_and_deep(self):
        p = self.install("--dry-run", "--vulkan", "--with-deep", "--no-voice")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("podman pull ghcr.io/ggml-org/llama.cpp:server-vulkan", p.stdout)
        self.assertIn("download mradermacher/VibeThinker-3B-GGUF", p.stdout); self.assertIn("[vibethinker]", p.stdout)
        self.assertNotIn("prefetch.py", p.stdout); self.assertIn("skipped (--no-voice)", p.stdout)

    def test_missing_prerequisite_is_reported_and_nothing_is_done(self):
        os.remove(os.path.join(self.tools, "jq"))
        p = self.install("--cpu")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("Missing: jq", p.stderr); self.assertIn("Only Fedora 44 has been tested", p.stderr)
        self.assertNotIn("podman pull", self.stub_log())

    def test_missing_voice_tools_only_warn(self):
        os.remove(os.path.join(self.tools, "pw-record"))
        p = self.install("--dry-run", "--cpu")
        self.assertEqual(p.returncode, 0, p.stderr); self.assertIn("voice will not work", p.stderr)
        p = self.install("--dry-run", "--cpu", "--no-voice")
        self.assertNotIn("voice will not work", p.stderr)

    def test_not_enough_disk_space(self):
        p = self.install("--dry-run", "--cpu", TINKER_MIN_GB="99999999")
        self.assertNotEqual(p.returncode, 0); self.assertIn("GB free here", p.stderr)

    def test_incomplete_copy_of_the_project(self):
        os.remove(os.path.join(self.proj, "images", "decider", "Containerfile"))
        p = self.install("--dry-run", "--cpu")
        self.assertNotEqual(p.returncode, 0); self.assertIn("images/decider/Containerfile", p.stderr)


class TestProfiles(Base):
    def test_auto_detects_vulkan_when_a_render_node_exists(self):
        p = self.install("--dry-run")
        self.assertIn("trying Vulkan", p.stdout); self.assertIn("PROFILE=vulkan", p.stdout)

    def test_auto_detects_cpu_without_a_render_node(self):
        p = self.install("--dry-run", TINKER_DRI_GLOB=os.path.join(self.tmp, "nothing-*"))
        self.assertIn("using CPU", p.stdout); self.assertIn("PROFILE=cpu", p.stdout)

    def test_auto_falls_back_to_cpu_when_the_probe_finds_no_vulkan(self):
        p = self.install("--no-voice", "--skip-selftest", STUB_VULKAN="0")
        self.assertEqual(p.returncode, 0, p.stderr); self.assertIn("falling back to the CPU profile", p.stderr)
        self.assertIn("PROFILE=cpu", self.read("config/tinker.env"))

    def test_forced_vulkan_without_a_device_fails_clearly(self):
        p = self.install("--vulkan", "--no-voice", "--skip-selftest", STUB_VULKAN="0")
        self.assertNotEqual(p.returncode, 0); self.assertIn("--vulkan was requested", p.stderr)

    def test_thread_counts_follow_the_cpu_count(self):
        p = self.install("--cpu", "--no-voice", "--skip-selftest")
        self.assertEqual(p.returncode, 0, p.stderr)
        n = os.cpu_count() or 4
        env = self.read("config/tinker.env")
        self.assertIn(f"LLM_THREADS={max(2, n // 2)}", env); self.assertIn(f"DECIDER_THREADS={max(2, n * 2 // 3)}", env)


class TestFullRun(Base):
    def test_creates_config_link_and_calls_the_right_tools(self):
        p = self.install("--cpu", "--no-voice", "--skip-selftest")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.proj, ".venv", "bin", "python")))
        ini = self.read("config/models.ini")
        self.assertIn("[minicpm5]\nmodel = /models/llm/MiniCPM5-2B-Q4_K_M.gguf", ini)
        self.assertIn("model = /models/llm/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf", ini); self.assertNotIn("vibethinker", ini)
        link = os.path.join(self.home, ".local", "bin", "tinker")
        self.assertEqual(os.path.realpath(link), os.path.join(os.path.realpath(self.proj), "bin", "tinker"))
        log = self.stub_log()
        self.assertIn("podman pull ghcr.io/ggml-org/llama.cpp:server\n", log); self.assertNotIn("server-vulkan", log)
        self.assertIn("podman pull ghcr.io/amir20/dozzle:latest", log)
        self.assertIn("podman build -t localhost/tinker-decider", log); self.assertIn("tinker build", log)

    def test_with_deep_adds_vibethinker(self):
        p = self.install("--cpu", "--no-voice", "--skip-selftest", "--with-deep")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("[vibethinker]\nmodel = /models/llm/VibeThinker-3B.Q4_K_M.gguf", self.read("config/models.ini"))
        self.assertIn("mradermacher/VibeThinker-3B-GGUF", self.stub_log())

    def test_rerun_skips_finished_downloads_and_is_stable(self):
        self.assertEqual(self.install("--cpu", "--no-voice", "--skip-selftest").returncode, 0)
        first = self.stub_log().count("hf download")
        self.assertEqual(first, 3)
        ini = self.read("config/models.ini")
        p = self.install("--cpu", "--no-voice", "--skip-selftest")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.stub_log().count("hf download"), first)       # nothing downloaded again
        self.assertEqual(self.read("config/models.ini"), ini)
        self.assertFalse(os.path.exists(os.path.join(self.proj, "config", "models.ini.bak")))

    def test_changed_models_ini_is_backed_up(self):
        self.assertEqual(self.install("--cpu", "--no-voice", "--skip-selftest").returncode, 0)
        self.assertEqual(self.install("--cpu", "--no-voice", "--skip-selftest", "--with-deep").returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.proj, "config", "models.ini.bak")))

    def test_failed_download_stops_with_a_clear_message(self):
        p = self.install("--cpu", "--no-voice", "--skip-selftest", STUB_HF_FAIL="1")
        self.assertNotEqual(p.returncode, 0); self.assertIn("download failed", p.stderr)
        self.assertNotIn("podman build", self.stub_log())

    def test_alias_is_added_once_to_the_right_rc_file(self):
        for _ in range(2):
            self.assertEqual(self.install("--cpu", "--no-voice", "--skip-selftest", "--alias", SHELL="/usr/bin/zsh").returncode, 0)
        with open(os.path.join(self.home, ".zshrc")) as f:
            self.assertEqual(f.read().count("alias Tinker='tinker'"), 1)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".bashrc")))

    def test_alias_is_only_suggested_without_the_flag(self):
        p = self.install("--cpu", "--no-voice", "--skip-selftest")
        self.assertIn("optional:", p.stdout); self.assertFalse(os.path.exists(os.path.join(self.home, ".bashrc")))


class Quiet(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class FirstOptionDecider(Quiet):
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send([{"choice": q["options"][0], "confidence": 0.9} for q in req["questions"]])


class HelloLLM(Quiet):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send({"choices": [{"message": {"content": "Hello from the mock."}}]})


class TestSelfTestAndUninstall(Base):
    @classmethod
    def setUpClass(cls):
        cls.servers = []
        for handler in (FirstOptionDecider, HelloLLM):
            srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers.append(srv)
        cls.decider_url, cls.llm_url = (f"http://127.0.0.1:{s.server_address[1]}" for s in cls.servers)

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers:
            s.shutdown(); s.server_close()

    def test_selftest_passes_when_vela_answers(self):
        p = self.install("--cpu", "--no-voice", TINKER_LLM=self.llm_url, TINKER_DECIDER=self.decider_url)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("PASS: Tinker answered: tinker> Hello from the mock.", p.stdout)
        log = self.stub_log(); self.assertIn("tinker up", log); self.assertIn("tinker off", log)

    def test_selftest_fails_loudly_when_vela_does_not_answer(self):
        p = self.install("--cpu", "--no-voice", TINKER_LLM=self.llm_url, TINKER_DECIDER="http://127.0.0.1:9")
        self.assertNotEqual(p.returncode, 0); self.assertIn("SELF-TEST FAILED", p.stderr)
        self.assertIn("tinker off", self.stub_log())                          # the stack is still stopped afterwards

    def test_uninstall_removes_pods_images_and_link_but_not_the_folder(self):
        os.makedirs(os.path.join(self.home, ".local", "bin"))
        link = os.path.join(self.home, ".local", "bin", "tinker"); os.symlink(os.path.join(self.proj, "bin", "tinker"), link)
        os.makedirs(os.path.join(self.proj, "models", "llm")); keep = os.path.join(self.proj, "models", "llm", "m.gguf"); open(keep, "w").close()
        p = self.install("--uninstall", "--purge-images")
        self.assertEqual(p.returncode, 0, p.stderr)
        log = self.stub_log()
        for expect in ("pod rm -f tinker-brain tinker-observe", "rmi localhost/tinker-decider", "rmi ghcr.io/ggml-org/llama.cpp:server-vulkan"):
            self.assertIn(expect, log)
        self.assertFalse(os.path.lexists(link)); self.assertTrue(os.path.exists(keep))

    def test_plain_uninstall_keeps_the_llama_images(self):
        self.install("--uninstall")
        self.assertNotIn("llama.cpp", self.stub_log())


class TestPipAndBuildBehaviour(Base):
    def test_core_and_voice_requirements_go_into_one_pip_call(self):
        out = self.install("--dry-run", "--cpu").stdout
        line = next(l for l in out.splitlines() if "pip install" in l)
        self.assertIn("requirements.txt", line); self.assertIn("requirements-voice.txt", line)
        self.assertEqual(sum("pip install" in l for l in out.splitlines()), 1)

    def test_no_voice_installs_only_the_core_requirements(self):
        out = self.install("--dry-run", "--cpu", "--no-voice").stdout
        line = next(l for l in out.splitlines() if "pip install" in l)
        self.assertNotIn("requirements-voice.txt", line)

    def test_steps_show_elapsed_seconds(self):
        self.assertRegex(self.install("--dry-run", "--cpu").stdout, r"==> 1/10 .*\[\d+s\]")


class TestVelaScriptProfiles(Base):
    """bin/tinker build with a CPU or Vulkan config: which image, device and flags does podman get?"""
    def setUp(self):
        super().setUp()
        write_exec(os.path.join(self.tools, "curl"), "#!/bin/sh\necho OK\n")          # the podman API 'ping' succeeds
        os.makedirs(os.path.join(self.proj, "models", "decider-2b"))
        open(os.path.join(self.proj, "models", "decider-2b", "decider-2b-v11-Q8_0.gguf"), "w").close()

    def build(self, env_file):
        with open(os.path.join(self.proj, "config", "tinker.env"), "w") as f:
            f.write(env_file)
        p = subprocess.run(["bash", os.path.join(self.proj, "bin", "tinker"), "build"], env=self.env(),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return [l for l in self.stub_log().splitlines() if "tinker-llm" in l or "tinker-decider" in l]

    def test_cpu_profile_has_no_device_and_no_gpu_layers(self):
        llm, decider = self.build("PROFILE=cpu\nLLM_THREADS=3\nDECIDER_THREADS=5\n")
        self.assertIn("ghcr.io/ggml-org/llama.cpp:server --models-preset", llm); self.assertIn("-t 3", llm)
        self.assertNotIn("--device", llm); self.assertNotIn("-ngl", llm); self.assertNotIn("server-vulkan", llm)
        self.assertIn("THREADS=5", decider); self.assertIn("DECIDER_GGUF=/model/decider-2b-v11-Q8_0.gguf", decider)

    def test_vulkan_profile_passes_the_device_and_offloads_layers(self):
        llm, decider = self.build("PROFILE=vulkan\nLLM_THREADS=6\nDECIDER_THREADS=8\n")
        self.assertIn("--device /dev/dri", llm); self.assertIn("llama.cpp:server-vulkan", llm); self.assertIn("-ngl 99", llm)
        self.assertIn("THREADS=8", decider)

    def test_build_creates_containers_without_starting_or_stopping_them(self):
        self.build("PROFILE=cpu\n")
        log = self.stub_log()
        self.assertEqual(log.count("podman create --pod"), 3)               # llm, decider, dozzle
        self.assertNotIn("podman run -d", log)
        self.assertNotIn("pod stop", log)                                    # nothing was started, so nothing to stop

    def test_missing_decider_model_is_explained(self):
        os.remove(os.path.join(self.proj, "models", "decider-2b", "decider-2b-v11-Q8_0.gguf"))
        p = subprocess.run(["bash", os.path.join(self.proj, "bin", "tinker"), "build"], env=self.env(),
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(p.returncode, 0); self.assertIn("Decider model not found", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
