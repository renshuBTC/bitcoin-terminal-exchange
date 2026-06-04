#!/usr/bin/env bash
#
# Install a pre-commit hook that runs `npm run audit` (which runs
# scripts/audit.py — the Tailwind tokens + import/export cross-checks).
#
# Opt-in: contributors run `bash btx-web/scripts/install-precommit.sh`
# once from the repo root. The hook lives in `.git/hooks/pre-commit` and
# is NOT tracked in the repo (git won't let you).
#
# What the hook does:
#   - Cd into btx-web/ and runs audit.py
#   - If either audit reports a real issue, the commit aborts
#   - If both pass, the commit proceeds
#
# Bypass with `git commit --no-verify` if you need to. The hook is
# advisory, not a security boundary.

set -euo pipefail

# Find the repo root regardless of where this script is invoked from.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
hook_path="$repo_root/.git/hooks/pre-commit"

if [[ ! -d "$repo_root/.git" ]]; then
  echo "error: $repo_root is not a git repository (no .git/ found)" >&2
  exit 1
fi

cat > "$hook_path" <<'HOOK'
#!/usr/bin/env bash
# btx-web audit pre-commit hook (installed by btx-web/scripts/install-precommit.sh).
# Bypass with `git commit --no-verify` if you need to.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
audit="$repo_root/btx-web/scripts/audit.py"

if [[ ! -f "$audit" ]]; then
  # audit script missing; let the commit through but warn.
  echo "warning: $audit not found; skipping btx-web audit" >&2
  exit 0
fi

# Only run when btx-web/ files are part of this commit.
staged="$(git diff --cached --name-only)"
if ! echo "$staged" | grep -q '^btx-web/'; then
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "warning: python3 not found on PATH; skipping btx-web audit" >&2
  exit 0
fi

echo "==> btx-web audit (Tailwind tokens + import/export wiring)"
python3 "$audit"
HOOK

chmod +x "$hook_path"

echo "Installed pre-commit hook at $hook_path"
echo "Try it: stage a change inside btx-web/ then run \`git commit\`."
echo "Bypass with \`git commit --no-verify\`."
