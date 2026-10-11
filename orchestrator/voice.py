"""Mic (pw-record) -> STT (Whisper base by default, Parakeet optional) ; text -> Piper TTS -> speaker (pw-play)."""
import glob, os, re, shutil, signal, subprocess, tempfile, time, wave
import numpy as np
from settings import HOME

os.environ.setdefault("HF_HOME", os.path.join(HOME, "models", "speech", "hf"))   # keep downloads inside the project
IN_WAV = os.path.join(tempfile.gettempdir(), "tinker_in.wav")
OUT_WAV = os.path.join(tempfile.gettempdir(), "tinker_out.wav")
VOICE = os.environ.get("TINKER_VOICE") or os.path.join(HOME, "voices", "en_US-lessac-medium.onnx")
STT = os.environ.get("TINKER_STT", "whisper")                       # whisper | parakeet
LANG = os.environ.get("TINKER_LANG", "en")
HINT = os.environ.get("TINKER_HINT", "Tinker, podman, Python, bash, email")   # words Whisper should expect
MIC = ["--target", os.environ["TINKER_MIC"]] if os.environ.get("TINKER_MIC") else []
FIXES = [(re.compile(r"\b(feela|veela|vella|fela)\b", re.I), "Tinker"),
         (re.compile(r"\b(hey|hi|okay|ok)[, ]+villa\b", re.I), r"\1 Tinker"),
         (re.compile(r"\b(portman|port man|pod man)\b", re.I), "podman")]
_stt = _tts = None


def _read_wav(path):
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def _load_stt():
    if STT == "parakeet":
        import onnx_asr
        m = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8")
        return lambda path: m.recognize(path)
    from faster_whisper import WhisperModel
    try:                                                   # cached: load from disk, NO network call
        m = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
    except Exception:                                      # first run: download it once
        m = WhisperModel("base", device="cpu", compute_type="int8")
    def run(path):
        segs, _ = m.transcribe(_read_wav(path), beam_size=1, language=LANG, initial_prompt=HINT or None)
        return " ".join(s.text.strip() for s in segs)
    return run


def _fix(text):
    for pat, rep in FIXES:
        text = pat.sub(rep, text)
    return text


def _normalize(path, target=0.7, max_gain=20.0):
    """Boost quiet clips (clipping can't be undone, quiet can) and report the mic peak. Returns the peak."""
    with wave.open(path, "rb") as w:
        params = w.getparams()
    a = _read_wav(path)
    peak = float(np.abs(a).max()) if a.size else 0.0
    if 0.01 < peak < target:
        gain = min(target / peak, max_gain)
        print(f"mic peak {peak*100:.0f}% -> boosted x{gain:.1f}")
        with wave.open(path, "wb") as w:
            w.setparams(params); w.writeframes((np.clip(a * gain, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
    else:
        print(f"mic peak {peak*100:.0f}%" + ("   (CLIPPING: lower the mic level)" if peak > 0.98 else ""))
    return peak


def listen():
    global _stt
    if _stt is None:
        _stt = _load_stt()
    input("[Enter] then speak... ")
    p = subprocess.Popen(["pw-record", *MIC, "--rate", "16000", "--channels", "1", "--format", "s16", IN_WAV])
    input("[Enter] to stop.   ")
    p.send_signal(signal.SIGINT); p.wait()
    peak = _normalize(IN_WAV)
    cdir = os.path.join(HOME, "state", "clips"); os.makedirs(cdir, exist_ok=True)
    shutil.copy(IN_WAV, os.path.join(cdir, time.strftime("heard-%H%M%S.wav")))      # last 30 kept, for testing
    for old in sorted(glob.glob(os.path.join(cdir, "heard-*.wav")))[:-30]:
        os.remove(old)
    if peak < 0.01:
        print("(nothing recorded: is the mic muted?)"); return ""
    raw = (_stt(IN_WAV) or "").strip()
    fixed = _fix(raw)
    if fixed != raw:
        print(f"(corrected from: {raw!r})")
    return fixed


def speak(text):
    global _tts
    from piper import PiperVoice
    if _tts is None:
        _tts = PiperVoice.load(VOICE)
    with wave.open(OUT_WAV, "wb") as w:
        _tts.synthesize_wav(text, w)
    subprocess.run(["pw-play", OUT_WAV], check=False)
