#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
# No production credentials or endpoint access: tests use temporary bare repositories.
python3 -B verify_ci_inputs.py
python3 --version
git --version
for mode in normal optimized; do
  if [[ $mode == optimized ]]; then opt=(-O); else opt=(); fi
  python3 -B "${opt[@]}" -m unittest discover -s tests -p 'test_*.py' -v
  python3 -B "${opt[@]}" test_partial_clone.py
  printf 'XRAY_SOURCE_ISOLATED_PUBLISHER_%s_PASS\n' "$mode"
done
