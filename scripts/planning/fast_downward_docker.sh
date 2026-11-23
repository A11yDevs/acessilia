#!/usr/bin/env bash
# Fast Downward from the pinned aibasel/downward image, as a drop-in
# executable for FastDownwardPlanner (#790).
#
#   ACESSILIA_FAST_DOWNWARD="$PWD/scripts/planning/fast_downward_docker.sh" \
#     uv run --extra dev pytest -m fast_downward tests/test_fast_downward_domain.py
#
# The planner passes the domain and the problem as absolute paths and reads
# sas_plan from its working directory, so the working directory and the
# directory of each file argument are mounted at the same paths.
# FAST_DOWNWARD_IMAGE overrides the image, e.g. to try a newer release.
set -euo pipefail

image="${FAST_DOWNWARD_IMAGE:-aibasel/downward@sha256:328732c5cb87e8c34f477a88a4f99977b6ea91ca5c1e859b886b5334c42d80e8}"

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
  "${mounts[@]}" -w "$PWD" "$image" "$@"
