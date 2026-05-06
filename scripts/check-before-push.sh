#!/usr/bin/env bash
# scripts/check-before-push.sh
#
# Run before every git push to catch truncation/syntax errors.
#
# Usage (from repo root):
#   bash scripts/check-before-push.sh
#
# Install as automatic pre-push hook (run once):
#   cp scripts/check-before-push.sh .git/hooks/pre-push
#   chmod +x .git/hooks/pre-push

ERRORS=0
RED='\033[0;31m'
GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'

fail() { printf "${RED}  FAIL${NC}  %s\n" "$1"; ERRORS=$((ERRORS+1)); }
ok()   { printf "${GREEN}    OK${NC}  %s\n" "$1"; }

# --- Vue SFC structure -------------------------------------------------------
printf "\n${BOLD}Vue SFC structure${NC}\n"
while IFS= read -r -d '' f; do
  name="${f#./}"
  # Anchor to start-of-line so inner <template v-if> / <template #slot> don't count
  tmpl=$(grep -c  '^<template'  "$f" || true)
  etmpl=$(grep -c '^</template>' "$f" || true)
  scr=$(grep -c   '^<script'    "$f" || true)
  escr=$(grep -c  '^</script>'  "$f" || true)
  sty=$(grep -c   '^<style'     "$f" || true)
  esty=$(grep -c  '^</style>'   "$f" || true)
  bad=0
  [ "$tmpl"  -ne 1 ] && { fail "$name: $tmpl <template> tags (need 1)"; bad=1; }
  [ "$etmpl" -ne 1 ] && { fail "$name: $etmpl </template> tags (need 1)"; bad=1; }
  [ "$scr"   -lt 1 ] && { fail "$name: missing <script>"; bad=1; }
  [ "$escr"  -lt 1 ] && { fail "$name: missing </script>"; bad=1; }
  [ "$sty" -gt 0 ] && [ "$esty" -ne "$sty" ] && { fail "$name: $sty <style> but $esty </style>"; bad=1; }
  [ "$bad" -eq 0 ] && ok "$name"
done < <(find ./frontend/src -name '*.vue' -print0 2>/dev/null)

# --- Python syntax -----------------------------------------------------------
printf "\n${BOLD}Python syntax${NC}\n"
while IFS= read -r -d '' f; do
  name="${f#./}"
  err=$(python3 -m py_compile "$f" 2>&1 || true)
  if [ -z "$err" ]; then
    ok "$name"
  else
    fail "$name: $err"
  fi
done < <(find ./backend -name '*.py' -not -path '*/__pycache__/*' -print0 2>/dev/null)

# --- Summary -----------------------------------------------------------------
printf "\n"
if [ "$ERRORS" -gt 0 ]; then
  printf "${RED}${BOLD}FAILED: %d error(s). Fix before pushing.${NC}\n" "$ERRORS"
  exit 1
else
  printf "${GREEN}${BOLD}All checks passed. Safe to push.${NC}\n"
  exit 0
fi
