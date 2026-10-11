<!--
  PRs are squash-merged with a Conventional Commits title, e.g.:
    feat(voice): add a wake word
    fix(install): detect Vulkan on Arch
    docs(models): record the code benchmark for Gemma 4
  See CONTRIBUTING.md for the full list of types.
-->

## What this changes

<!-- one or two sentences -->

## Type

- [ ] feat
- [ ] fix
- [ ] docs
- [ ] bench
- [ ] test
- [ ] refactor
- [ ] perf
- [ ] chore
- [ ] breaking change (explain below)

## Testing

```
$ bash tests/run_all.sh
<paste the summary lines>
```

- [ ] A test was added or updated for this change
- [ ] Docs were updated if behaviour, a file, or a config field changed

## Benchmark evidence (if this changes a model, prompt, or sampler setting)

<!-- command you ran and the before/after numbers, e.g. output of bench/code_bench.py -->

## Hardware (if relevant: install.sh, bin/tinker, or anything hardware-specific)

- OS / distro:
- `podman --version`:
- CPU / RAM / GPU:
- Profile (`config/tinker.env`):
