#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./setup_and_push.sh --repo <owner/repo> [--branch main] [--visibility private|public|internal] [--message "Initial commit"]

Examples:
  ./setup_and_push.sh --repo jamisonfitz/marquee --visibility public
  ./setup_and_push.sh --repo jamisonfitz/marquee --branch main --message "Initial commit"

Requirements:
  gh installed and authenticated with `gh auth login`
EOF
}

repo=""
branch="main"
visibility="public"
message="Initial commit"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --branch)
      branch="${2:-}"
      shift 2
      ;;
    --visibility)
      visibility="${2:-}"
      shift 2
      ;;
    --message)
      message="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${repo}" ]]; then
  usage
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  cat <<'EOF'
GitHub CLI (gh) is not installed.
Install it first, then run gh auth login, then rerun this script.
EOF
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is installed but not authenticated. Run: gh auth login"
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
  git commit -m "${message}"
  has_head=1
fi

if [[ ${has_head} -eq 0 ]]; then
  echo "Nothing to publish: the repository has no commits and no staged changes."
  exit 1
fi

git branch -M "${branch}"

desired_url="https://github.com/${repo}.git"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "${desired_url}"
else
  git remote add origin "${desired_url}"
fi

if ! gh repo view "${repo}" >/dev/null 2>&1; then
  case "${visibility}" in
    private)
      gh repo create "${repo}" --source . --private
      ;;
    public)
      gh repo create "${repo}" --source . --public
      ;;
    internal)
      gh repo create "${repo}" --source . --internal
      ;;
    *)
      echo "Invalid visibility: ${visibility}"
      exit 1
      ;;
  esac
fi

git push -u origin "${branch}"

