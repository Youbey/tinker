#!/usr/bin/env bash
# Run every offline test file, each in its own process (they each set up their own temp project folder).
cd "$(dirname "$0")/.." || exit 1
rc=0
for t in tests/test_tinker.py tests/test_bench.py tests/test_voice.py tests/test_docs.py tests/test_install.py; do
  printf '%-24s ' "$t"
  if python3 "$t" >/tmp/tinker-test.log 2>&1; then grep -E '^Ran ' /tmp/tinker-test.log | tr '\n' ' '; echo "OK"
  else echo "FAILED"; tail -n 25 /tmp/tinker-test.log; rc=1; fi
done
exit $rc
