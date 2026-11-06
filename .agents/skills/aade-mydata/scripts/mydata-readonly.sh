#!/bin/sh
set -eu
skill_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
repo_dir=$(CDPATH= cd -- "$skill_dir/../../.." && pwd)
if [ -x "$repo_dir/.venv/bin/mydata-readonly" ]; then
    runtime="$repo_dir/.venv/bin/mydata-readonly"
elif command -v mydata-readonly >/dev/null 2>&1; then
    runtime=$(command -v mydata-readonly)
else
    echo 'myDATA read-only runtime is missing; see references/runtime.md.' >&2
    exit 2
fi
export MYDATA_READ_ONLY=1
exec "$runtime" "$@"
