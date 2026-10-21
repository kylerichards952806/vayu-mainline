#!/usr/bin/env bash
# Overlay the imported vayu board description onto a kernel tree.
#
#   ./scripts/prepare-tree.sh <dest> [base] [--with-config]
#
#   dest          directory to clone into (created if missing)
#   base          android17-6.18 (default) | android16-6.12 | android15-6.6 |
#                 linux-6.18.y | linux-6.12.y | mainline
#   --with-config merge import/config/... over an arm64 defconfig (needs make+clang)
#
# The tree is cloned with --depth 1: this repo only ever builds against the tip
# of a branch, and a full kernel history is ~4 GB.
set -euo pipefail

usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

[ $# -ge 1 ] || usage
DEST=$1; shift
BASE=${1:-android17-6.18}; [ $# -gt 0 ] && shift
WITH_CONFIG=0
for arg in "$@"; do
    case "$arg" in
        --with-config) WITH_CONFIG=1 ;;
        *) echo "unknown option: $arg" >&2; usage ;;
    esac
done

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FRAGMENT="$ROOT/import/config/config-postmarketos-qcom-sm8150.aarch64"

case "$BASE" in
    android*)  URL=https://android.googlesource.com/kernel/common ;;
    linux-*)   URL=https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git ;;
    mainline)  URL=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git; BASE=master ;;
    *) echo "unsupported base: $BASE" >&2; usage ;;
esac

if [ -d "$DEST/.git" ]; then
    echo "==> reusing existing tree $DEST ($(git -C "$DEST" rev-parse --short HEAD))"
else
    echo "==> cloning $BASE from $URL"
    git clone --depth 1 --branch "$BASE" "$URL" "$DEST"
fi

QCOM="$DEST/arch/arm64/boot/dts/qcom"
[ -d "$QCOM" ] || { echo "no $QCOM — wrong base?" >&2; exit 1; }

echo "==> overlaying vayu DTS"
# dts/ is the working copy; import/dts/ is the untouched upstream snapshot it
# was forked from (diff the two to see every rebase change).
cp "$ROOT"/dts/*.dts "$QCOM"/

if ! grep -q 'sm8150-xiaomi-vayu.dtb' "$QCOM/Makefile"; then
    echo "==> registering sm8150-xiaomi-vayu.dtb in $QCOM/Makefile"
    printf 'dtb-$(CONFIG_ARCH_QCOM) += sm8150-xiaomi-vayu.dtb\n' >> "$QCOM/Makefile"
fi

if [ "$WITH_CONFIG" = 1 ]; then
    echo "==> merging imported config over arm64 defconfig"
    make -C "$DEST" ARCH=arm64 LLVM=1 defconfig
    "$DEST/scripts/kconfig/merge_config.sh" -m -O "$DEST" \
        "$DEST/.config" "$FRAGMENT"
    make -C "$DEST" ARCH=arm64 LLVM=1 olddefconfig
fi

cat <<EOF

==> ready: $DEST ($(git -C "$DEST" rev-parse --short HEAD) on $BASE)

    cd $DEST
    make -j"\$(nproc)" ARCH=arm64 LLVM=1 dtbs    # fast sanity check
    make -j"\$(nproc)" ARCH=arm64 LLVM=1 Image   # full kernel
EOF
