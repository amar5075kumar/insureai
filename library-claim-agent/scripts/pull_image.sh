#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Reliable Docker image puller for WSL2 environments with flaky networks.
#
# Uses curl with retries to download image layers individually, then loads
# them into Docker via `docker load`. This bypasses Docker daemon's Go HTTP
# client which fails on WSL2 low-MTU networks.
#
# Usage:
#   ./scripts/pull_image.sh postgres:16-alpine
#   ./scripts/pull_image.sh minio/minio:latest
#   ./scripts/pull_image.sh livekit/livekit-server:latest
#
# First tries `docker pull` (fast if network is fine).
# Falls back to curl-based pull if that fails.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

FULL_IMAGE="${1:?Usage: $0 IMAGE:TAG}"
# Parse repo and tag
TAG="${FULL_IMAGE##*:}"
REPO="${FULL_IMAGE%:*}"
[ "$TAG" = "$FULL_IMAGE" ] && TAG="latest"

# Prefix with library/ for official images (no slash in name)
REGISTRY_REPO="$REPO"
[[ "$REPO" != *"/"* ]] && REGISTRY_REPO="library/$REPO"

DISPLAY_NAME="$REPO:$TAG"

# ── Check if already cached ──────────────────────────────────────────────────
if docker images --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | grep -qF "$DISPLAY_NAME"; then
    echo "✓ $DISPLAY_NAME already cached"
    exit 0
fi

# ── Try native docker pull first (fast path) ─────────────────────────────────
echo "→ Pulling $DISPLAY_NAME (trying docker pull first)..."
if timeout 60 docker pull "$DISPLAY_NAME" 2>/dev/null; then
    echo "✓ $DISPLAY_NAME pulled via docker"
    exit 0
fi
echo "  docker pull failed — falling back to curl-based pull"

# ── Curl-based pull with retries ─────────────────────────────────────────────
WORKDIR=$(mktemp -d)
trap "rm -rf $WORKDIR" EXIT

rcurl() {
    # Silent retry curl — tries up to 8 times with 2s backoff
    for attempt in $(seq 1 8); do
        if result=$(curl -sfSL --http1.1 --connect-timeout 10 --max-time 120 "$@" 2>/dev/null) && [ -n "$result" ]; then
            echo "$result"
            return 0
        fi
        [ $attempt -lt 8 ] && sleep 2
    done
    return 1
}

rcurl_file() {
    local url="$1" dest="$2"
    for attempt in $(seq 1 8); do
        if curl -fSL --http1.1 --retry 3 --retry-delay 2 --retry-all-errors \
             --connect-timeout 10 --max-time 600 \
             -H "Authorization: Bearer $TOKEN" \
             -o "$dest" "$url" 2>/dev/null && [ -s "$dest" ]; then
            return 0
        fi
        sleep 2
    done
    echo "  ERROR: download failed after retries: $(basename "$url" | cut -c1-20)" >&2
    return 1
}

# 1. Auth token
echo "  [1/5] Auth..."
TOKEN=$(rcurl "https://auth.docker.io/token?scope=repository:${REGISTRY_REPO}:pull&service=registry.docker.io" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')

# 2. Manifest list → find amd64 digest
echo "  [2/5] Manifest..."
MFST=$(rcurl -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.index.v1+json" \
    "https://registry-1.docker.io/v2/${REGISTRY_REPO}/manifests/${TAG}")

AMD64=$(echo "$MFST" | python3 -c "
import json,sys
m = json.load(sys.stdin)
if 'manifests' in m:
    for mm in m['manifests']:
        p = mm.get('platform',{})
        if p.get('architecture')=='amd64' and p.get('os')=='linux':
            v = p.get('variant','')
            if not v or v in ('v1','v2','v3','v4'):
                print(mm['digest']); break
elif 'layers' in m:
    print('DIRECT')
" 2>/dev/null)

[ -z "$AMD64" ] && { echo "ERROR: no amd64 manifest for $DISPLAY_NAME"; exit 1; }

if [ "$AMD64" != "DIRECT" ]; then
    MFST=$(rcurl -H "Authorization: Bearer $TOKEN" \
        -H "Accept: application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.manifest.v1+json" \
        "https://registry-1.docker.io/v2/${REGISTRY_REPO}/manifests/${AMD64}")
fi

# 3. Parse config + layer digests
echo "  [3/5] Parsing..."
CONFIG_DIGEST=$(echo "$MFST" | python3 -c "import json,sys;print(json.load(sys.stdin)['config']['digest'])")
LAYER_DIGESTS=$(echo "$MFST" | python3 -c "
import json,sys
for l in json.load(sys.stdin)['layers']: print(l['digest'])
")
NUM_LAYERS=$(echo "$LAYER_DIGESTS" | wc -l)
echo "         $NUM_LAYERS layers"

# 4. Download config
echo "  [4/5] Config..."
rcurl_file "https://registry-1.docker.io/v2/${REGISTRY_REPO}/blobs/${CONFIG_DIGEST}" "$WORKDIR/config.json"

# 5. Download layers
echo "  [5/5] Layers..."
mkdir -p "$WORKDIR/layers"
i=0
while IFS= read -r digest; do
    i=$((i+1))
    printf "         %d/%d %s " "$i" "$NUM_LAYERS" "${digest:7:12}"
    rcurl_file "https://registry-1.docker.io/v2/${REGISTRY_REPO}/blobs/${digest}" "$WORKDIR/layers/${i}.tar.gz"
    du -h "$WORKDIR/layers/${i}.tar.gz" | cut -f1
done <<< "$LAYER_DIGESTS"

# 6. Assemble OCI tarball → docker load
echo "  Assembling..."
CONFIG_HASH=${CONFIG_DIGEST#sha256:}
LAYER_PATHS=""
i=0
while IFS= read -r digest; do
    i=$((i+1))
    HASH=${digest#sha256:}
    mkdir -p "$WORKDIR/img/$HASH"
    cp "$WORKDIR/layers/${i}.tar.gz" "$WORKDIR/img/$HASH/layer.tar"
    [ -n "$LAYER_PATHS" ] && LAYER_PATHS="${LAYER_PATHS},"
    LAYER_PATHS="${LAYER_PATHS}\"${HASH}/layer.tar\""
done <<< "$LAYER_DIGESTS"

cp "$WORKDIR/config.json" "$WORKDIR/img/${CONFIG_HASH}.json"
cat > "$WORKDIR/img/manifest.json" << MEOF
[{"Config":"${CONFIG_HASH}.json","RepoTags":["${DISPLAY_NAME}"],"Layers":[${LAYER_PATHS}]}]
MEOF

tar cf "$WORKDIR/image.tar" -C "$WORKDIR/img" .
echo "  Loading into Docker..."
docker load < "$WORKDIR/image.tar"
echo "✓ $DISPLAY_NAME ready"
