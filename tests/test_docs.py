"""Offline tests that keep the documentation, config examples, .gitignore and LICENSE consistent with the code.
Run:  python3 tests/test_docs.py"""
import json, os, re, shutil, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))   # for test_install
import settings                                                     # noqa: E402
import test_install as T                                            # reuse its stub podman/hf/curl, same as the installer tests

DOCS = ["README.md", "CONTRIBUTING.md", "docs/MODELS.md"]
GENERATED = {"config/models.ini", "config/tinker.env", "config/models.ini.bak"}     # written by install.sh, not in the repo
COMMANDS = ["build", "on", "speak", "chat", "up", "off", "status", "logs"]


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kw)


class TestReadmeMatchesTheCode(unittest.TestCase):
    def test_every_installer_option_is_documented(self):
        helptext = run(["bash", os.path.join(ROOT, "install.sh"), "--help"]).stdout
        flags = set(re.findall(r"--[a-z][a-z-]+", helptext)) - {"--help"}
        self.assertGreaterEqual(len(flags), 8, helptext)
        readme = read("README.md")
        self.assertEqual([f for f in sorted(flags) if f"`{f}`" not in readme], [])

    def test_every_vela_command_is_documented(self):
        usage = run(["bash", os.path.join(ROOT, "bin", "tinker")]).stdout
        readme = read("README.md")
        for cmd in COMMANDS:
            self.assertIn(cmd, usage, f"{cmd} is not in the script's usage text")
            self.assertIn(f"`tinker {cmd}", readme, f"`tinker {cmd}` is not in the README")

    def test_every_skill_field_and_output_mode_is_documented(self):
        readme = read("README.md")
        for name in (*settings.REQUIRED, "route_description", "announce", "extra", *settings.OUTPUTS):
            self.assertIn(f"`{name}`", readme, name)

    def test_every_benchmark_script_is_documented(self):
        readme = read("README.md")
        for f in sorted(os.listdir(os.path.join(ROOT, "bench"))):
            if f.endswith(".py") and f != "common.py":
                self.assertIn(f"bench/{f}", readme, f)

    def test_the_skill_example_in_the_readme_loads_and_is_routable(self):
        m = re.search(r"<!-- skill-example -->\s*```json\n(.*?)```", read("README.md"), re.S)
        self.assertIsNotNone(m, "the README lost its <!-- skill-example --> block")
        extra = json.loads("{" + m.group(1) + "}")
        cfg = json.loads(read("config/skills.json"))
        cfg["skills"].update(extra)
        tmp = tempfile.mkdtemp(prefix="tinker-docs-test-")
        try:
            path = os.path.join(tmp, "skills.json")
            with open(path, "w") as f:
                json.dump(cfg, f)
            loaded = settings.load(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn(next(iter(extra)), [n for n, s in loaded["skills"].items() if s.get("route_description")])


class TestMermaidDiagram(unittest.TestCase):
    """Structural checks only (no mermaid.js here): README.md keeps exactly one valid-looking flowchart block
    with balanced brackets and no raw double quotes inside a label (GitHub's renderer fails silently on that;
    use the #quot; entity instead, as Mermaid's own docs recommend)."""

    def block(self):
        m = re.search(r"```mermaid\n(.*?)```", read("README.md"), re.S)
        self.assertIsNotNone(m, "README.md has no ```mermaid block")
        return m.group(1)

    def test_exactly_one_mermaid_block(self):
        self.assertEqual(read("README.md").count("```mermaid"), 1)

    def test_declares_a_diagram_type(self):
        first_line = self.block().strip().splitlines()[0]
        self.assertRegex(first_line, r"^(flowchart|graph)\s+(TD|TB|LR|RL|BT)")

    def test_brackets_are_balanced(self):
        src = self.block()
        for open_c, close_c in [("[", "]"), ("{", "}"), ("(", ")")]:
            self.assertEqual(src.count(open_c), src.count(close_c), f"unbalanced {open_c}{close_c}")

    def test_no_raw_double_quotes_inside_labels(self):
        # A label written as ["He said \"hi\""] breaks GitHub's renderer; use #quot; instead.
        for line in self.block().splitlines():
            m = re.search(r'\[\s*"(.*)"\s*\]', line.strip())
            if m:
                self.assertNotIn('\\"', line, f"escaped quote inside a label: {line.strip()}")

    def test_classdef_targets_are_defined_nodes(self):
        # class E1,E2,E3 model  ->  E1/E2/E3 must actually appear as node definitions somewhere.
        src = self.block()
        defined = set(re.findall(r"\b([A-Za-z]\w*)[\[{(]", src))
        for line in src.splitlines():
            m = re.match(r"\s*class\s+([\w,]+)\s+\w+", line)
            if m:
                for node in m.group(1).split(","):
                    self.assertIn(node.strip(), defined, f"'class' targets undefined node {node!r}")


class TestFilesMentionedExist(unittest.TestCase):
    def test_backticked_repo_paths_exist(self):
        for doc in DOCS:
            for path in re.findall(r"`((?:bench|config|orchestrator|tests|images|docs|bin)/[A-Za-z0-9_./-]+)`", read(doc)):
                if path in GENERATED:
                    continue
                self.assertTrue(os.path.exists(os.path.join(ROOT, path)), f"{doc} mentions {path}, which does not exist")

    def test_relative_links_resolve(self):
        for doc in DOCS:
            for target in re.findall(r"\]\(([^)#\s]+)\)", read(doc)):
                if target.startswith("http"):
                    continue
                base = os.path.dirname(os.path.join(ROOT, doc))
                self.assertTrue(os.path.exists(os.path.join(base, target)), f"{doc} links to {target}")

    def test_the_project_layout_block_lists_real_paths(self):
        block = re.search(r"## Project layout\s*```\n(.*?)```", read("README.md"), re.S).group(1)
        for line in block.splitlines():
            first = line.split()[0].rstrip("/")
            self.assertTrue(os.path.exists(os.path.join(ROOT, first)), f"layout lists {first}")

    def test_no_personal_absolute_paths_in_shipped_files(self):
        files = ["install.sh", "bin/tinker", "config/skills.json", "config/models.example.ini", *DOCS]
        for d in ("orchestrator", "bench", "images/decider"):
            files += [os.path.join(d, f) for f in os.listdir(os.path.join(ROOT, d)) if f != "__pycache__"]
        for rel in files:
            self.assertIsNone(re.search(r"/home/[A-Za-z0-9_-]+", read(rel)), f"{rel} contains a personal /home/... path")


class TestConfigFilesAgree(unittest.TestCase):
    def test_every_model_used_by_a_skill_is_in_the_example_models_ini(self):
        cfg = settings.load(os.path.join(ROOT, "config", "skills.json"))
        used = {s["model"] for s in cfg["skills"].values()} | {cfg["multi_step"]["planner_model"]}
        sections = set(re.findall(r"^\[(\w+)\]", read("config/models.example.ini"), re.M))
        self.assertEqual(sorted(used - sections), [])

    def test_the_installer_downloads_every_model_the_example_lists(self):
        """Runs against the SAME stub podman/hf/curl as the installer tests, so this needs no real Podman."""
        case = T.Base(); case.setUp()
        try:
            dry = case.install("--dry-run", "--cpu", "--with-deep", "--no-voice")
        finally:
            case.tearDown()
        self.assertIn("would write config/models.ini", dry.stdout, dry.stderr)
        written = set(re.findall(r"^\s+\[(\w+)\]", dry.stdout, re.M))
        listed = set(re.findall(r"^\[(\w+)\]", read("config/models.example.ini"), re.M))
        self.assertEqual(written, listed)


class TestContributingAndTemplates(unittest.TestCase):
    def test_pr_template_exists_and_lists_every_commit_type(self):
        pr = read(".github/PULL_REQUEST_TEMPLATE.md")
        contrib = read("CONTRIBUTING.md")
        types = set(re.findall(r"^\| `(\w+)` \|", contrib, re.M))
        self.assertGreaterEqual(len(types), 8)
        for t in types:
            self.assertIn(f"[ ] {t}", pr, f"PR template is missing the '{t}' checkbox")

    def test_issue_templates_exist(self):
        for name in ("bug_report.md", "benchmark_results.md"):
            path = os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", name)
            self.assertTrue(os.path.isfile(path), name)
            with open(path) as f:
                self.assertTrue(f.read().startswith("---\n"), f"{name} needs YAML front matter")

    def test_contributing_mentions_conventional_commits(self):
        self.assertIn("Conventional Commits", read("CONTRIBUTING.md"))


class TestGitignoreAndLicense(unittest.TestCase):
    def test_gitignore_lists_all_personal_and_generated_data(self):
        lines = {l.strip() for l in read(".gitignore").splitlines()}
        for entry in (".venv/", "models/", "voices/", "state/", "logs/", "out/", "config/models.ini", "config/tinker.env"):
            self.assertIn(entry, lines)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_a_real_git_repo_would_not_track_personal_data(self):
        tmp = tempfile.mkdtemp(prefix="tinker-git-test-")
        try:
            repo = os.path.join(tmp, "repo")
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
            for rel in ("models/llm/m.gguf", "voices/v.onnx", "state/clips/heard-1.wav", "logs/trace.jsonl",
                        "out/answer.md", "config/models.ini", "config/tinker.env", ".venv/bin/python", "models/llm/.cache/x"):
                path = os.path.join(repo, rel); os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "w").close()
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            self.assertEqual(run(["git", "init", "-q"], cwd=repo, env=env).returncode, 0)
            run(["git", "add", "-A"], cwd=repo, env=env)
            tracked = run(["git", "ls-files"], cwd=repo, env=env).stdout.split()
            for bad in ("models/llm/m.gguf", "voices/v.onnx", "state/clips/heard-1.wav", "logs/trace.jsonl",
                        "out/answer.md", "config/models.ini", "config/tinker.env", ".venv/bin/python", "models/llm/.cache/x"):
                self.assertNotIn(bad, tracked)
            for good in ("README.md", "LICENSE", "NOTICE", "install.sh", "bin/tinker", "config/skills.json",
                         "config/models.example.ini", "orchestrator/tinker.py", "images/decider/Containerfile", ".gitignore"):
                self.assertIn(good, tracked)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_license_is_the_apache_2_text(self):
        text = read("LICENSE")
        self.assertIn("Apache License\n                           Version 2.0, January 2004", text)
        for n in range(1, 10):
            self.assertRegex(text, rf"(?m)^   {n}\. [A-Z]")
        self.assertIn("END OF TERMS AND CONDITIONS", text)
        self.assertEqual(len(text.splitlines()), 202)                # the canonical file is 202 lines
        self.assertIn("Apache License, Version 2.0", read("NOTICE"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
