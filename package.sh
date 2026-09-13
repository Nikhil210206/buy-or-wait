#!/usr/bin/env bash
# Build code.zip for submission.
#
# Includes the solution, prompts, README and the required evaluation/ folder.
# Excludes the dataset corpus, media, virtualenvs and build artifacts, per the
# submission instructions.
set -euo pipefail
cd "$(dirname "$0")"

rm -f code.zip

if [[ ! -s code/evaluation/usage_report.md ]]; then
  echo "error: code/evaluation/usage_report.md is missing or empty." >&2
  echo "       run: python3 code/evaluation/report.py" >&2
  exit 1
fi

zip -r code.zip code README.md \
  -x '*/__pycache__/*' '*.pyc' '*/.venv/*' '*/node_modules/*' \
     'code/cache/usage.json.bak' '*.DS_Store' >/dev/null

# Belt and braces: make sure nothing secret rode along.
if unzip -l code.zip | grep -qiE '\.env($|[^.])'; then
  echo "error: .env found inside code.zip -- refusing to ship" >&2
  rm -f code.zip
  exit 1
fi

echo "built code.zip ($(du -h code.zip | cut -f1))"
unzip -l code.zip | awk 'NR>3 && NF==4 && $4 != "" {print "  " $4}'
