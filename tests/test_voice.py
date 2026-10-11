"""Offline test: Whisper is loaded from disk first, and the network is used only when the model is not cached.
Uses a stub faster_whisper module, so no model or network is needed.  Run:  python3 tests/test_voice.py"""
import os, shutil, sys, tempfile, types, unittest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
TMP = tempfile.mkdtemp(prefix="tinker-voice-test-")
os.environ["TINKER_HOME"] = TMP
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))

try:
    import numpy                                                       # noqa: F401
    import voice
except ImportError:
    voice = None


class FakeModel:
    calls, cached = [], True

    def __init__(self, size, device="cpu", compute_type="int8", local_files_only=False):
        FakeModel.calls.append(local_files_only)
        if local_files_only and not FakeModel.cached:
            raise RuntimeError("model not in the local cache")

    def transcribe(self, *a, **k):
        return [], None


@unittest.skipUnless(voice, "numpy not installed")
class TestWhisperLoadsLocallyFirst(unittest.TestCase):
    def setUp(self):
        FakeModel.calls = []
        sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=FakeModel)
        self._stt = voice.STT; voice.STT = "whisper"

    def tearDown(self):
        voice.STT = self._stt; sys.modules.pop("faster_whisper", None)

    def test_cached_model_uses_no_network(self):
        FakeModel.cached = True
        voice._load_stt()
        self.assertEqual(FakeModel.calls, [True])                      # one local load, nothing else

    def test_uncached_model_is_downloaded_once(self):
        FakeModel.cached = False
        voice._load_stt()
        self.assertEqual(FakeModel.calls, [True, False])               # local attempt failed, then the one download


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
