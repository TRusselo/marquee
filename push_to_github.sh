#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./push_to_github.sh <github-remote-url> [branch] [commit-message]

Examples:
  ./push_to_github.sh git@github.com:jamisonfitz/marquee.git
  ./push_to_github.sh https://github.com/jamisonfitz/marquee.git main "Initial commit"

Notes:
  Use ./setup_and_push.sh for first-time GitHub repo creation.
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

remote_url="${1:-${GITHUB_REMOTE_URL:-}}"
branch="${2:-${GITHUB_BRANCH:-main}}"
commit_message="${3:-${GIT_COMMIT_MESSAGE:-Initial commit}}"

if [[ -z "${remote_url}" ]]; then
  usage
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${repo_root}" ]]; then
  repo_root="$(pwd)"
  git init
fi

cd "${repo_root}"

has_head=0
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  has_head=1
fi

git add -A
if ! git diff --cached --quiet; then
  git commit -m "${commit_message}"
  has_head=1
fi

if [[ ${has_head} -eq 0 ]]; then
  echo "Nothing to push: the repository has no commits and no staged changes."
  exit 1
fi

git branch -M "${branch}"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "${remote_url}"
else
  git remote add origin "${remote_url}"
fi

git push -u origin "${branch}"
