#!/usr/bin/env bash
# Tinker installer. Safe to re-run: finished steps are skipped.
#
#   ./install.sh                 detect hardware, install everything, run a self-test
#   ./install.sh --dry-run       print every action without doing anything
#   ./install.sh --cpu|--vulkan  force the llama.cpp profile (default: auto-detect)
#   ./install.sh --no-voice      text-only install (skips speech packages and models)
#   ./install.sh --with-deep     also download VibeThinker-3B (1.8 GB) for "think hard" requests
#   ./install.sh --alias         add  alias Tinker='tinker'  to your shell rc file
#   ./install.sh --skip-selftest don't start the stack and ask a question at the end
#   ./install.sh --uninstall     remove pods, the Decider image and the command link (keeps this folder and models)
#   ./install.sh --uninstall --purge-images   also remove the llama.cpp and Dozzle images
#
# Never uses sudo. Touches only: this folder, container images in Podman storage, ~/.local/bin/tinker,
# and (only with --alias) one line in your shell rc file.
set -uo pipefail

V="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PROFILE=auto; DRY=0; VOICE=1; DEEP=0; ALIAS=0; SELFTEST=1; UNINSTALL=0; PURGE=0; FORCED=0
IMG_VULKAN="ghcr.io/ggml-org/llama.cpp:server-vulkan"
IMG_CPU="ghcr.io/ggml-org/llama.cpp:server"
IMG_DOZZLE="ghcr.io/amir20/dozzle:latest"
PY="$V/.venv/bin/python"
HF="${TINKER_HF_BIN:-$V/.venv/bin/hf}"
TINKER_BIN="${TINKER_BIN:-$V/bin/tinker}"
DRI_GLOB="${TINKER_DRI_GLOB:-/dev/dri/renderD*}"
MIN_GB="${TINKER_MIN_GB:-20}"
export HF_HOME="$V/models/speech/hf"                 # keep every download inside this folder
export PIP_DISABLE_PIP_VERSION_CHECK=1

say()  { printf '\n==> %s   [%ss]\n' "$*" "$SECONDS"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
run()  { printf '  + %s\n' "$*"; [ "$DRY" = 1 ] && return 0; "$@"; }
pick() { compgen -G "$1" 2>/dev/null | head -n1; }   # first file matching a glob, or nothing

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --cpu) PROFILE=cpu; FORCED=1 ;;
    --vulkan) PROFILE=vulkan; FORCED=1 ;;
    --no-voice) VOICE=0 ;;
    --with-deep) DEEP=1 ;;
    --alias) ALIAS=1 ;;
    --skip-selftest) SELFTEST=0 ;;
    --uninstall) UNINSTALL=1 ;;
    --purge-images) PURGE=1 ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
  say "Removing Tinker's pods and images"
  run podman pod rm -f tinker-brain tinker-observe || true
  run podman rmi localhost/tinker-decider || true
  if [ "$PURGE" = 1 ]; then run podman rmi "$IMG_VULKAN" "$IMG_CPU" "$IMG_DOZZLE" || true; fi
  [ -L "$HOME/.local/bin/tinker" ] && run rm "$HOME/.local/bin/tinker"
  say "Done. Not removed (yours to delete): this folder $V (models, logs, recordings),"
  note "and the  alias Tinker=...  line in your shell rc file, if you added one."
  exit 0
fi

# ---------------------------------------------------------------- 1. code integrity
say "1/10  Checking this copy of the project"
for f in orchestrator/tinker.py orchestrator/settings.py config/skills.json images/decider/Containerfile images/decider/server.py bin/tinker requirements.txt; do
  [ -f "$V/$f" ] || die "missing $f: is this a complete copy of the project?"
done
if python3 "$V/tests/test_tinker.py" >/dev/null 2>&1; then note "offline tests pass"; else die "the offline tests fail: run  python3 tests/test_tinker.py  to see why"; fi

# ---------------------------------------------------------------- 2. prerequisites
say "2/10  Checking prerequisites (nothing is installed for you)"
missing=(); voice_missing=()
for c in podman curl jq python3; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
if [ "$VOICE" = 1 ]; then for c in pw-record pw-play; do command -v "$c" >/dev/null 2>&1 || voice_missing+=("$c"); done; fi
if command -v python3 >/dev/null 2>&1 && ! python3 -m venv --help >/dev/null 2>&1; then missing+=("python3-venv"); fi
if command -v podman >/dev/null 2>&1; then
  [ "$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" = true ] \
    || die "Podman must run rootless (as your normal user). Try:  podman info"
  note "podman: $(podman --version)  (rootless)"
fi
if [ "${#missing[@]}" -gt 0 ] || [ "${#voice_missing[@]}" -gt 0 ]; then
  . /etc/os-release 2>/dev/null
  printf '\nMissing: %s\n' "${missing[*]:-} ${voice_missing[*]:-}" >&2
  case "${ID:-}" in
    fedora) echo "On Fedora:  sudo dnf install podman curl jq python3 pipewire-utils" >&2 ;;
    *)      echo "Install: podman (rootless), curl, jq, python3 with venv support, and PipeWire's pw-record/pw-play for voice." >&2 ;;
  esac
  echo "(Only Fedora 44 has been tested. Voice tools are not needed with --no-voice.)" >&2
  [ "${#missing[@]}" -gt 0 ] && exit 1
  warn "voice tools missing: continuing, but voice will not work until you install them"
fi
avail_gb=$(( $(df -Pk "$V" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
[ "$avail_gb" -ge "$MIN_GB" ] || die "only ${avail_gb} GB free here; about ${MIN_GB} GB are needed (models, images, venv)"
note "disk: ${avail_gb} GB free"

# ---------------------------------------------------------------- 3. profile
say "3/10  Choosing the llama.cpp profile"
if [ "$PROFILE" = auto ]; then
  if ls $DRI_GLOB >/dev/null 2>&1; then PROFILE=vulkan; note "a GPU render node was found: trying Vulkan"; else PROFILE=cpu; note "no GPU render node: using CPU"; fi
fi
if [ "$PROFILE" = vulkan ]; then
  run podman pull "$IMG_VULKAN" || die "could not pull $IMG_VULKAN"
  if [ "$DRY" = 1 ] || podman run --rm --device /dev/dri "$IMG_VULKAN" --list-devices 2>&1 | grep -qi vulkan; then
    note "Vulkan device visible inside the container"
  elif [ "$FORCED" = 1 ]; then
    die "--vulkan was requested, but no Vulkan device is visible inside the container. Use --cpu, or see: podman run --rm --device /dev/dri $IMG_VULKAN --list-devices"
  else
    warn "no Vulkan device visible inside the container: falling back to the CPU profile"; PROFILE=cpu
  fi
fi
NPROC="$(nproc 2>/dev/null || echo 4)"
LLM_THREADS=$(( NPROC / 2 )); [ "$LLM_THREADS" -lt 2 ] && LLM_THREADS=2
DECIDER_THREADS=$(( NPROC * 2 / 3 )); [ "$DECIDER_THREADS" -lt 2 ] && DECIDER_THREADS=2
note "profile: $PROFILE | $NPROC CPU threads -> llama.cpp $LLM_THREADS, decider $DECIDER_THREADS"

# ---------------------------------------------------------------- 4. python
say "4/10  Python environment (inside $V/.venv)"
[ -x "$PY" ] || run python3 -m venv "$V/.venv" || die "could not create the virtual environment"
# ONE pip call, so pip resolves core + voice packages as a single consistent set (separate calls left conflicting versions)
reqs=(-r "${TINKER_REQUIREMENTS:-$V/requirements.txt}")
[ "$VOICE" = 1 ] && reqs+=(-r "$V/requirements-voice.txt")
run "$PY" -m pip install --quiet "${reqs[@]}" || die "pip install failed: see the message above"

# ---------------------------------------------------------------- 5. models
say "5/10  Downloading models (about 7 GB; re-running resumes and skips finished files)"
[ "$DRY" = 1 ] || mkdir -p "$V/models/llm" "$V/models/decider-2b"
if [ -z "$(pick "$V/models/llm/MiniCPM5-2B-Q4_K_M.gguf")" ]; then
  run "$HF" download openbmb/MiniCPM5-2B-GGUF MiniCPM5-2B-Q4_K_M.gguf --local-dir "$V/models/llm" || die "MiniCPM5 download failed"
else note "MiniCPM5: already here"; fi
if [ -z "$(pick "$V/models/llm/gemma-4-E4B-it-qat-UD-Q4_K_XL*.gguf")" ]; then
  run "$HF" download unsloth/gemma-4-E4B-it-qat-GGUF --include "*UD-Q4_K_XL*" --local-dir "$V/models/llm" || die "Gemma download failed"
else note "Gemma 4 E4B: already here"; fi
if [ -z "$(pick "$V/models/decider-2b/*Q8_0.gguf")" ]; then
  run "$HF" download Mapika/decider-2b-GGUF --local-dir "$V/models/decider-2b" \
      --include "*Q8_0.gguf" --include "*.json" --include "*.jinja" --include "*.py" || die "Decider download failed"
else note "Decider-2B: already here"; fi
if [ "$DEEP" = 1 ]; then
  if [ -z "$(pick "$V/models/llm/VibeThinker-3B.Q4_K_M.gguf")" ]; then
    run "$HF" download mradermacher/VibeThinker-3B-GGUF VibeThinker-3B.Q4_K_M.gguf --local-dir "$V/models/llm" || die "VibeThinker download failed"
  else note "VibeThinker: already here"; fi
fi

# ---------------------------------------------------------------- 6. voice assets
if [ "$VOICE" = 1 ]; then
  say "6/10  Voice models (Whisper base, Piper voice)"
  run "$PY" "$V/orchestrator/prefetch.py" || die "Whisper download failed"
  if [ -z "$(pick "$V/voices/en_US-lessac-medium.onnx")" ]; then
    run "$PY" -m piper.download_voices en_US-lessac-medium --data-dir "$V/voices" || die "Piper voice download failed"
  else note "Piper voice: already here"; fi
else
  say "6/10  Voice models: skipped (--no-voice)"
fi

# ---------------------------------------------------------------- 7. images
say "7/10  Container images"
[ "$PROFILE" = vulkan ] && LLM_IMAGE="$IMG_VULKAN" || LLM_IMAGE="$IMG_CPU"
run podman pull "$LLM_IMAGE" || die "pull failed: $LLM_IMAGE"
run podman pull "$IMG_DOZZLE" || die "pull failed: $IMG_DOZZLE"
note "building the Decider image (a few minutes: it compiles llama-cpp-python)"
run podman build -t localhost/tinker-decider "$V/images/decider" || die "the Decider image failed to build"

# ---------------------------------------------------------------- 8. config files
say "8/10  Writing config"
mini="$(pick "$V/models/llm/MiniCPM5-2B-Q4_K_M.gguf")"; gemma="$(pick "$V/models/llm/gemma-4-E4B-it-qat-UD-Q4_K_XL*.gguf")"
deep="$(pick "$V/models/llm/VibeThinker-3B.Q4_K_M.gguf")"
if [ "$DRY" = 1 ]; then
  mini="${mini:-MiniCPM5-2B-Q4_K_M.gguf}"; gemma="${gemma:-gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf}"
  [ "$DEEP" = 1 ] && deep="${deep:-VibeThinker-3B.Q4_K_M.gguf}"
fi
[ -n "$mini" ] && [ -n "$gemma" ] || die "a model file is missing from $V/models/llm: re-run ./install.sh to finish the download"
models_ini="$(printf '[minicpm5]\nmodel = /models/llm/%s\n\n[gemma4]\nmodel = /models/llm/%s\n' "$(basename "$mini")" "$(basename "$gemma")"
              [ -n "$deep" ] && printf '\n[vibethinker]\nmodel = /models/llm/%s\n' "$(basename "$deep")")"
vela_env="$(printf '# Written by install.sh. Edit freely, then run:  tinker build\nPROFILE=%s\nLLM_THREADS=%s\nDECIDER_THREADS=%s\n' "$PROFILE" "$LLM_THREADS" "$DECIDER_THREADS")"
if [ "$DRY" = 1 ]; then
  note "would write config/models.ini:"; printf '%s\n' "$models_ini" | sed 's/^/      /'
  note "would write config/tinker.env:";   printf '%s\n' "$vela_env"   | sed 's/^/      /'
else
  mkdir -p "$V/config"
  [ -f "$V/config/models.ini" ] && ! printf '%s\n' "$models_ini" | cmp -s - "$V/config/models.ini" && cp "$V/config/models.ini" "$V/config/models.ini.bak" && note "kept the old models.ini as models.ini.bak"
  printf '%s\n' "$models_ini" > "$V/config/models.ini"
  printf '%s\n' "$vela_env" > "$V/config/tinker.env"
  note "wrote config/models.ini and config/tinker.env"
fi
if [ "$DEEP" = 0 ] && [ -z "$deep" ]; then note "VibeThinker not installed: 'think hard' requests will report a missing model (add it with --with-deep)"; fi

# ---------------------------------------------------------------- 9. command + alias
say "9/10  The tinker command"
run mkdir -p "$HOME/.local/bin"
run ln -sf "$V/bin/tinker" "$HOME/.local/bin/tinker"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "$HOME/.local/bin is not on your PATH: add it, or run $V/bin/tinker directly" ;; esac
if [ "$ALIAS" = 1 ]; then
  rc="$HOME/.bashrc"; case "${SHELL:-}" in */zsh) rc="$HOME/.zshrc" ;; esac
  if [ "$DRY" = 1 ]; then note "would add  alias Tinker='tinker'  to $rc"
  elif grep -q "^alias Tinker=" "$rc" 2>/dev/null; then note "alias already in $rc"
  else printf "alias Tinker='tinker'\n" >> "$rc"; note "added the alias to $rc (open a new shell)"; fi
else
  note "optional:  echo \"alias Tinker='tinker'\" >> ~/.zshrc     (or re-run with --alias)"
fi
run "$TINKER_BIN" build || die "tinker build failed"

# ---------------------------------------------------------------- 10. self-test
say "10/10  Self-test"
if [ "$SELFTEST" = 0 ] || [ "$DRY" = 1 ]; then
  note "skipped"
else
  "$TINKER_BIN" up || die "the stack did not start: see  tinker logs tinker-llm  and  tinker logs tinker-decider"
  out="$("$PY" "$V/orchestrator/tinker.py" --once "hello there" 2>&1)"; rc=$?
  "$TINKER_BIN" off >/dev/null 2>&1
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q '^tinker> .\+'; then
    note "PASS: Tinker answered: $(printf '%s\n' "$out" | grep -m1 '^tinker> ')"
  else
    printf '%s\n' "$out" | tail -n 8 >&2
    die "SELF-TEST FAILED: the stack started but Tinker did not answer (output above)"
  fi
fi

say "Installed ($PROFILE profile)."
note "Try:   tinker chat     (type, silent)    tinker speak (type, hear)    tinker on (voice)"
note "Logs:  http://127.0.0.1:9999 (Dozzle, while the stack is up)    Stop: tinker off"
[ "$DRY" = 1 ] && note "(dry run: nothing was changed)"
exit 0
