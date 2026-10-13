#!/usr/bin/env bash
set -uo pipefail

# Harbor collects the verifier reward from this mounted log location.
REWARD_DIR="/logs/verifier"
REWARD_FILE="${REWARD_DIR}/reward.txt"
mkdir -p "${REWARD_DIR}"

# Ensure a reward file exists even if pytest fails or exits unexpectedly.
printf '0\n' > "${REWARD_FILE}"

if pytest -q /tests/test_task.py; then
  printf '1\n' > "${REWARD_FILE}"
  exit 0
else
  status=$?
  printf '0\n' > "${REWARD_FILE}"
  exit "${status}"
fi
