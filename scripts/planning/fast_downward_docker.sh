#!/usr/bin/env bash
# Fast Downward from the pinned aibasel/downward image, as a drop-in
# executable for FastDownwardPlanner (#790). Needs Docker; on an ARM machine
# the amd64 image runs under emulation.
#
#   ACESSILIA_FAST_DOWNWARD="$PWD/scripts/planning/fast_downward_docker.sh" \
#     uv run --extra dev pytest -m fast_downward tests/test_fast_downward_domain.py
#
# The planner passes the domain and the problem as absolute paths and reads
# sas_plan from its working directory, so the working directory and the
# directory of each file argument are mounted at the same paths.
# The image comes from fast_downward.env; FAST_DOWNWARD_IMAGE overrides it, e.g.
# to try a newer release (CI sets it from that file explicitly).
set -euo pipefail

if [ -z "${FAST_DOWNWARD_IMAGE:-}" ]; then
  env_file="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fast_downward.env"
  FAST_DOWNWARD_IMAGE=$(sed -n 's/^FAST_DOWNWARD_IMAGE=//p' "$env_file")
fi
test -n "$FAST_DOWNWARD_IMAGE"

seen=" $PWD "
mounts=(-v "$PWD:$PWD")
for arg in "$@"; do
  if [ -f "$arg" ]; then
    dir=$(cd "$(dirname "$arg")" && pwd)
    case "$seen" in
      *" $dir "*) ;;
      *) mounts+=(-v "$dir:$dir:ro"); seen="$seen$dir " ;;
    esac
  fi
done

# Files written in the mounted working directory belong to the caller.
exec docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" \
  "${mounts[@]}" -w "$PWD" "$FAST_DOWNWARD_IMAGE" "$@"
