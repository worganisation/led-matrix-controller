#!/usr/bin/env bash
set -euo pipefail

tag="${1:-}"
if [[ ! "$tag" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Expected a stable semantic release tag" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=normal --ignore-submodules=untracked)" ]]; then
  echo "Working tree is dirty; preserve local changes before deploying" >&2
  exit 1
fi

git fetch --prune --tags origin
target="$(git rev-parse --verify "refs/tags/${tag}^{commit}")"
if ! git merge-base --is-ancestor "$target" origin/main; then
  echo "Release tag is not on origin/main" >&2
  exit 1
fi

if ! git cat-file -e "${target}:scripts/deploy-release.sh"; then
  echo "Release tag does not contain the deployment entrypoint" >&2
  exit 1
fi

audio_processor=0
services=(led_matrix_controller.service)
if [[ -f /etc/systemd/system/audio_processor.service ]]; then
  audio_processor=1
  services+=(audio_processor.service)
fi

git switch --detach "$target"
make AP="$audio_processor" install-all
make AP="$audio_processor" restart

for service in "${services[@]}"; do
  pid="$(systemctl show --value --property=MainPID "$service")"
  restarts="$(systemctl show --value --property=NRestarts "$service")"
  if [[ ! "$pid" =~ ^[1-9][0-9]*$ || ! "$restarts" =~ ^[0-9]+$ ]]; then
    echo "$service did not start with a valid process" >&2
    exit 1
  fi

  sleep 10

  if ! systemctl is-active --quiet "$service" ||
    [[ "$(systemctl show --value --property=MainPID "$service")" != "$pid" ]] ||
    [[ "$(systemctl show --value --property=NRestarts "$service")" != "$restarts" ]]; then
    echo "$service exited or restarted during the deployment health check" >&2
    exit 1
  fi
done

echo "Deployed $tag ($target)"
