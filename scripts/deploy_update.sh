#!/usr/bin/env bash
# Controlled update of this single-user deployment. Never submits inference requests.
# Usage: sudo bash deploy_update.sh OLD_RELEASE SOURCE_TAR COMMIT TAR_SHA256 BASE_IMAGE_ID
set -euo pipefail
umask 077
old=$(realpath "${1:?Missing old release}")
archive=$(realpath "${2:?Missing source archive}")
revision=${3:?Missing commit}
archive_sha=${4:?Missing archive SHA256}
base_id=${5:?Missing base image ID}
[[ "$revision" =~ ^[a-f0-9]{40}$ && "$archive_sha" =~ ^[a-f0-9]{64}$ ]]
[[ "$base_id" =~ ^sha256:[a-f0-9]{64}$ ]]
printf '%s  %s\n' "$archive_sha" "$archive" | sha256sum --check --status
test -f "$old/.env.stage3"
base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["services"]["api"]["image"])' "$old/.local/prebuilt.json")
test "$(docker image inspect "$base" --format '{{.Id}}')" = "$base_id"
release="$(dirname "$old")/release-$revision"
test ! -e "$release"
mkdir -m 700 "$release"
tar -xzf "$archive" -C "$release"
# Dependency changes require the full Dockerfile build, not an application overlay.
for file in requirements.txt requirements-stage3.txt requirements-build.txt Dockerfile; do
    cmp "$old/$file" "$release/$file"
done
cp -a "$old/weights" "$release/weights"
cp -a "$old/data/raw" "$release/data/raw"
cp -a "$old/.env" "$old/.env.stage3" "$release/"
mkdir -p "$release/.local"
image="garbage-vision-stage3:gpu-${revision:0:12}"
python3 - "$release" "$image" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
p=root/'.env.stage3'
updates={'GV_S3_PAID_MODE':'manual','GV_S3_PAID_CALL_LIMIT':'0',
         'GV_S3_AUTHORIZATION_ID':'stage3-user-manual-20261022'}
lines=[line for line in p.read_text().splitlines() if line.partition('=')[0] not in updates]
p.write_text('\n'.join(lines+[f'{k}={v}' for k,v in updates.items()])+'\n')
(root/'.local/prebuilt.json').write_text(json.dumps({'services':{
    'api':{'image':sys.argv[2]},'web':{'image':sys.argv[2]}}}))
PY
cd "$release"
docker build --pull=false --network none -f deploy/Dockerfile.update \
    --build-arg "BASE_IMAGE=$base" --label "org.opencontainers.image.revision=$revision" \
    --label "org.opencontainers.image.base.digest=$base_id" -t "$image" .
docker run --rm --network none "$image" python -m pip check
compose=(docker compose -f compose.yaml -f compose.gpu.yaml -f .local/prebuilt.json)
"${compose[@]}" config --quiet
run="manual-update-$(date -u +%Y%m%dT%H%M%SZ)"
out="$release/evidence/stage3/remote-linux/$run"
mkdir -p "$out"
client() {
    docker run --rm --network host --user 0 --env-file "$1/.env.stage3" \
        -e GV_S3_API_URL=http://127.0.0.1:8080/api \
        --mount "type=bind,src=$1,dst=/app,readonly" \
        --mount "type=bind,src=$out,dst=/out" "$image" "${@:2}"
}
client "$old" python scripts/verify_stage3_maintenance.py snapshot /out
# On failure restore the old service; retain both data directories and all diagnostics.
recover_old() {
    status=$?
    if (( status != 0 )); then
        cd "$old"
        "${compose[@]}" up -d --no-build --pull never --force-recreate --wait --wait-timeout 180 || true
    fi
    exit "$status"
}
trap recover_old EXIT
cd "$old"
"${compose[@]}" stop web api
client "$old" python scripts/verify_stage3_maintenance.py backup /out
cp -a "$old/.local/container-data" "$release/.local/container-data"
cd "$release"
"${compose[@]}" up -d --no-build --pull never --force-recreate --wait --wait-timeout 180
client "$release" python scripts/verify_stage3_maintenance.py compare /out
docker run --rm --user 0 --network none \
    --mount "type=bind,src=$out/restore-copy,dst=/data" \
    --mount "type=bind,src=$release/scripts/verify_container_restore.py,dst=/verify_restore.py,readonly" \
    -e PYTHONPATH=/app "$image" python /verify_restore.py
client "$release" python -c 'import json; from pathlib import Path; from garbage_vision.service_client import request; r=request("GET","/health/ready").json(); assert r["paid_calls_mode"]=="manual" and r["paid_calls_enabled"] and r["paid_calls_remaining"] is None; Path("/out/capabilities.json").write_text(json.dumps(r,indent=2)); print("Manual mode enabled; verification created no tasks.")'
python3 - "$release" "$out" "$revision" "$image" "$base_id" "$archive_sha" <<'PY'
import hashlib,json,sqlite3,sys
from pathlib import Path
r,o=map(Path,sys.argv[1:3])
db=sqlite3.connect(f'file:{r}/.local/container-data/tasks.sqlite3?mode=ro',uri=True)
grants=db.execute('select id,call_limit,reserved from api_authorizations').fetchall()
assert not any(row[0]=='stage3-user-manual-20261022' for row in grants), 'Unexpected new paid task'
result={'complete':True,'application_commit':sys.argv[3],'image':sys.argv[4],
        'base_image_id':sys.argv[5],'source_archive_sha256':sys.argv[6],
        'paid_mode':'manual','new_paid_calls_during_update':0,
        'previous_authorizations':grants,'history_matches':True,
        'isolated_restore_passed':True,
        'runtime_sha256':{p:hashlib.sha256((r/p).read_bytes()).hexdigest()
                          for p in ('garbage_vision/service.py','stage3_app.py')}}
(o/'update-result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
PY
active=/home/ecs-user/gv-stage3-active
test ! -e "$active" || test -L "$active"
ln -s "$release" "$active.next"
mv -Tf "$active.next" "$active"
trap - EXIT
"${compose[@]}" ps
printf 'Update passed. Active release: %s\nEvidence: %s\n' "$release" "$out"
