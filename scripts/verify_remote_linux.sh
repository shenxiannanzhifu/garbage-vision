#!/usr/bin/env bash
# Run with sudo on the deployed server. Uses the existing image and real HTTP.
# No external model calls; maintenance never creates an inference task.
set -euo pipefail
umask 077
action=${1:?Usage: verify_remote_linux.sh local|maintenance RELEASE_DIR}
release=$(realpath "${2:?Missing release directory}")
cd "$release"
test -f .env.stage3
image=$(python3 -c 'import json;print(json.load(open(".local/prebuilt.json"))["services"]["api"]["image"])')
compose=(docker compose -f compose.yaml -f compose.gpu.yaml -f .local/prebuilt.json)
out="$release/evidence/stage3/remote-linux"
mkdir -p "$out"
client() {
    docker run --rm --network host --user 0 --env-file .env.stage3 \
        -e GV_S3_API_URL=http://127.0.0.1:8080/api \
        --mount "type=bind,src=$release,dst=/app,readonly" \
        --mount "type=bind,src=$out,dst=/out" "$image" "$@"
}
case "$action" in
local)
    # Resume recorded task IDs after interruption; do not rerun completed models.
    resume=()
    if test -f "$out/local/verification-progress.json"; then resume=(--resume); fi
    client python scripts/verify_stage3_http.py \
        data/raw/commons/commons-179028310.jpg data/raw/commons/commons-79273563.jpg \
        --output /out/local "${resume[@]}"
    ;;
maintenance)
    run="maintenance-$(date -u +%Y%m%dT%H%M%SZ)"
    client python scripts/verify_stage3_maintenance.py snapshot "/out/$run"
    # If backup fails, restore service availability before returning failure.
    trap '"${compose[@]}" start api >/dev/null || true' EXIT
    "${compose[@]}" stop api
    client python scripts/verify_stage3_maintenance.py backup "/out/$run"
    "${compose[@]}" up -d --no-build --pull never --force-recreate --wait --wait-timeout 180
    client python scripts/verify_stage3_maintenance.py compare "/out/$run"
    docker run --rm --user 0 --network none \
        --mount "type=bind,src=$out/$run/restore-copy,dst=/data" \
        --mount "type=bind,src=$release/scripts/verify_container_restore.py,dst=/verify_restore.py,readonly" \
        -e PYTHONPATH=/app "$image" python /verify_restore.py
    tar -czf "$out/$run/data-backup.tar.gz" -C "$out/$run" backup backup-manifest.json
    sha256sum "$out/$run/data-backup.tar.gz"
    trap - EXIT
    printf '%s\n' "Remote container recreation and isolated backup restore passed: $run"
    ;;
*) echo 'Action must be local or maintenance' >&2; exit 2 ;;
esac
