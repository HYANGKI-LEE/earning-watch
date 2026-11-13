#!/usr/bin/env bash
# 사용법: commit_data.sh "커밋 메시지" 파일...
# 파일이 있고 바뀌었을 때만 커밋·push (원격이 앞서 있으면 rebase 후 재시도)
set -u
msg="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
for f in "$@"; do [ -f "$f" ] && git add "$f"; done
if git diff --cached --quiet; then
  echo "변경 없음: $*"; exit 0
fi
git commit -m "$msg"
for i in 1 2 3; do
  git pull --rebase -X theirs origin main && git push && exit 0
  sleep 5
done
echo "push 실패" >&2; exit 1
