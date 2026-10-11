#!/usr/bin/env python3
"""Speech-to-text accuracy on YOUR voice.
  stt_bench.py record [--corpus DIR]                   read the sentences in bench/stt_sentences.txt aloud
  stt_bench.py eval whisper-base parakeet-int8 [...]   word error rate + speed per engine on those clips
Options for eval: --hint "words Whisper should expect"  --trim-start 0.25  --trim-end 0.25  --corpus DIR
Engines: whisper-base | whisper-small | parakeet-int8.  Numbers are normalized ("17x23" = "seventeen times twenty three").
Needs numpy; whisper engines need faster-whisper; parakeet needs onnx-asr[cpu,hub]."""
import argparse, glob, os, signal, subprocess, sys, time, wave
import numpy as np
from common import BENCH, HOME, edit_distance

os.environ.setdefault("HF_HOME", os.path.join(HOME, "models", "speech", "hf"))


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2), "expected 16 kHz mono 16-bit"
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def sentences():
    with open(os.path.join(BENCH, "stt_sentences.txt")) as f:
        return [l.strip() for l in f if l.strip()]


def record(corpus):
    os.makedirs(corpus, exist_ok=True)
    mic = ["--target", os.environ["TINKER_MIC"]] if os.environ.get("TINKER_MIC") else []
    print("Speak at your NORMAL volume and pace. Pause a beat after pressing Enter. Each sentence: Enter, speak, Enter.")
    for i, s in enumerate(sentences(), 1):
        wav = os.path.join(corpus, f"{i:02d}.wav")
        print(f"\n[{i}] Say:  {s}")
        input("  [Enter] to start... ")
        p = subprocess.Popen(["pw-record", *mic, "--rate", "16000", "--channels", "1", "--format", "s16", wav])
        input("  [Enter] to stop.   ")
        p.send_signal(signal.SIGINT); p.wait()
        with open(wav[:-4] + ".txt", "w") as f:
            f.write(s)
        a = read_wav(wav)
        print(f"  mic peak {np.abs(a).max() * 100:.0f}%  clipped samples {(np.abs(a) > 0.98).sum()}")
    print(f"\nSaved clips in {corpus}")


def trimmed(a, start, end):
    return a[int(start * 16000): len(a) - int(end * 16000)] if (start or end) else a


def load_engine(name, hint):
    if name.startswith("parakeet"):
        import onnx_asr
        m = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8")
        def run(a, path):
            tmp = "/tmp/tinker_stt_clip.wav"
            with wave.open(tmp, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
            return m.recognize(tmp)
        return run
    if name.startswith("whisper-"):
        from faster_whisper import WhisperModel
        size = name.split("-", 1)[1]
        try:
            m = WhisperModel(size, device="cpu", compute_type="int8", local_files_only=True)   # cached: no network
        except Exception:
            m = WhisperModel(size, device="cpu", compute_type="int8")
        return lambda a, path: " ".join(s.text.strip() for s in m.transcribe(a, beam_size=1, language="en", initial_prompt=hint or None)[0])
    sys.exit(f"unknown engine: {name}")


def evaluate(engines, corpus, hint, trim_start, trim_end):
    files = sorted(glob.glob(os.path.join(corpus, "*.wav")))
    if not files:
        sys.exit(f"no clips in {corpus}: run  stt_bench.py record  first")
    refs = []
    for f in files:
        with open(f[:-4] + ".txt") as fh:
            refs.append(fh.read().strip())
    audio = [trimmed(read_wav(f), trim_start, trim_end) for f in files]
    for name in engines:
        run = load_engine(name, hint); run(audio[0], files[0])        # warm-up
        err = tot = 0; secs = 0.0; bad = []
        for a, f, ref in zip(audio, files, refs):
            t = time.time(); hyp = (run(a, f) or "").strip(); secs += time.time() - t
            e, n = edit_distance(ref, hyp); err += e; tot += n
            if e:
                bad.append((ref, hyp))
        print(f"\n=== {name}: word error rate {100 * err / tot:.1f}% ({err}/{tot} words) | avg {secs / len(files):.2f}s per clip")
        for ref, hyp in bad:
            print(f"   said: {ref}\n   got : {hyp}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["record", "eval"]); ap.add_argument("engines", nargs="*")
    ap.add_argument("--corpus", default=os.path.join(HOME, "state", "corpus"))
    ap.add_argument("--hint"); ap.add_argument("--trim-start", type=float, default=0.0); ap.add_argument("--trim-end", type=float, default=0.0)
    a = ap.parse_args()
    record(a.corpus) if a.mode == "record" else evaluate(a.engines or ["whisper-base"], a.corpus, a.hint, a.trim_start, a.trim_end)
