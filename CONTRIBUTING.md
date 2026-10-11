# Contributing

Thanks for helping. Tinker is an alpha project: the most valuable contributions are **measurements** and **fixes for things that only break on other machines**.

## Run the tests first

```bash
bash tests/run_all.sh
```

They need no models, no network and no containers (mock servers and stub commands stand in for them). Please add a test with every change. Tests must be hermetic: they must not depend on files that only exist on your machine (a generated `config/models.ini`, your models, your recordings).

## Commit messages: Conventional Commits

Every commit on `main` follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer]
```

| Type | For |
|---|---|
| `feat` | a new feature |
| `fix` | a bug fix |
| `docs` | documentation only |
| `bench` | a new or changed benchmark, or new test data under `bench/*.json` |
| `test` | tests only, no behaviour change |
| `refactor` | neither a feature nor a fix, no behaviour change |
| `perf` | a performance improvement |
| `chore` | tooling, CI, dependency bumps |

`scope` is optional and names the area, e.g. `feat(voice): add a wake word`, `fix(install): detect Vulkan on Arch`, `bench(code): add a sorting task`. A `!` after the type or scope (`feat!:`) or a `BREAKING CHANGE:` footer marks a breaking change.

This is not bureaucracy for its own sake: it is what lets a changelog be generated from `git log` instead of written by hand, so keep the summary line readable on its own ("fix(voice): stop Whisper from calling the network when the model is cached", not "fix bug"). Pull requests are squash-merged with a Conventional Commits title, so the PR title is what ends up in history; the commits inside a PR do not need to follow the format individually.

## Pull requests

Use the PR template (fills in automatically). Before marking a PR ready:

- [ ] `bash tests/run_all.sh` passes
- [ ] a test was added or updated for the change
- [ ] docs were updated if behaviour, a file, or a config field changed (`tests/test_docs.py` checks some of this automatically)
- [ ] any new claim about speed or accuracy is backed by a `bench/` run, with the command and numbers in the PR description

## Useful contributions

- **Benchmark results from other hardware**: run `bench/routing_bench.py`, `bench/code_bench.py` and `bench/stt_bench.py` and open an issue with your CPU, RAM, GPU, distribution, `podman --version`, the profile (`config/tinker.env`), and the output.
- **Other distributions and Podman versions**: the installer is tested on Fedora 44 only. Fix package hints in `install.sh` and report what failed.
- **Better or smaller models** for a skill: change `config/skills.json` and `config/models.ini`, then show before/after numbers from `bench/`. Add cases to `bench/*.json` rather than editing the scripts.
- **NVIDIA and AMD container profiles** (the installer currently has CPU and Vulkan).
- **Voice activity detection and a wake word** instead of push-to-talk; **read-back confirmation** before any action; **tool calling**; document search.
- Other **speech engines** behind `orchestrator/voice.py`.

## Ground rules

- The orchestrator (`orchestrator/`) uses only the Python standard library, apart from `voice.py`.
- Model-specific behaviour (names, prompts, sampling) belongs in `config/skills.json`, not in code.
- Keep your own data out of commits: `models/`, `state/`, `logs/`, `out/` are git-ignored. Do not paste recordings or `trace.jsonl` into issues.
- Claims in documentation must come from a measurement or a link to the source. Say "not tested" when it is not.
- By contributing you agree that your contribution is licensed under the Apache License 2.0.
