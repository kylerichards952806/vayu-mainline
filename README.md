# vayu-mainline

Mainline / Android-Common-Kernel bringup work for the **Xiaomi POCO X3 Pro**
(`vayu` / `M2102J20SG`, Qualcomm **SM8150**), which currently runs a downstream
**5.4 QGKI** vendor kernel (`5.4.302-qgki_aman`, `techpack/*` + `qcacld-3.0`).

> **Status: seed only.** Nothing here boots yet. This repo holds the imported
> starting material, the CI that compiles it, and the plan.

Read [docs/ASSESSMENT.md](docs/ASSESSMENT.md) first — it answers "how easy is
this?" with numbers, and separates the two very different projects that the
phrase *"move vayu to mainline-android"* can mean.

## What is in here

| Path | What it is |
| --- | --- |
| `import/dts/sm8150-xiaomi-vayu.dts` | The **899-line, 106 KB** vayu device tree from the postmarketOS SM8150 tree, unmodified. The single most valuable artefact: it already describes the board (panel, touch, PMICs, regulators, reserved-memory carve-outs, UFS, USB, WCN3990). |
| `dts/sm8150-xiaomi-vayu.dts` | Working copy: the same file plus rebase fixes for 6.18. `diff -u import/dts dts` is the rebase log. |
| `import/config/config-postmarketos-qcom-sm8150.aarch64` | 7,968-line `defconfig`+`sm8150.config` merge from postmarketOS. Use as a base, not as-is. |
| `scripts/prepare-tree.sh` | Clones/overlays the DTS and config onto a chosen kernel base and prints the build commands. |
| `.github/workflows/build.yml` | Compiles the DTB (and optionally a full `Image`) against `android17-6.18`, `android-mainline`, or `linux-6.18.y`. |
| `docs/HARDWARE.md` | Per-subsystem status: what upstream already has for SM8150, what vayu needs on top, what is missing entirely. |
| `docs/PROVENANCE.md` | Exact upstream commits the imported files came from, and their licences. |

Everything in `import/` is GPL-2.0-only kernel source; this repo is therefore
GPL-2.0-only.

## Why not start from `torvalds/linux`

Starting from a pristine kernel means re-deriving vayu's board description from
the vendor DTS (≈6,000 lines of downstream SDE/KGSL/techpack properties, most of
which have no mainline equivalent). The postmarketOS SM8150 tree already did
that work for `sm8150.dtsi` + `pm8150*.dtsi` + vayu, on a 6.4 kernel. Rebasing
*that* forward is days; starting from zero is months.

## Quickstart (Linux host or CI)

```bash
# 1. pick a base and fetch it
./scripts/prepare-tree.sh /tmp/kernel android17-6.18

# 2. build the DTBs only (fast; this is what CI does by default)
cd /tmp/kernel
make -j"$(nproc)" ARCH=arm64 LLVM=1 dtbs

# 3. full kernel
make -j"$(nproc)" ARCH=arm64 LLVM=1 Image
```

There is **no local toolchain on the Windows dev box** (no `make`, no clang, no
WSL — see the 5.4 tree's `AUDIT.md` §5), so CI is the build path. Workflow
dispatch inputs: `base`, `full` (build `Image` too), `config` (merge the pmOS
config).

## First milestone`sm8150-xiaomi-vayu.dtb` compiles against `android17-6.18` with no binding
 errors. That is a real, checkable step: it proves the imported board description
is still valid against a 6.18-era `sm8150.dtsi`, before any boot attempt.

## Boot-image reality on this device

`vayu` has **no `vendor_boot` partition**. It boots a header-**v2** `boot.img`
with the ramdisk inside it, and a separate 32 MiB `dtbo` partition holding the
*vendor SDE* overlay. Mainline does not use that overlay:

- mainline boot images **append the DTB** to `boot.img` (`deviceinfo_append_dtb`,
  the postmarketOS convention for this device),
- the vendor `dtbo` becomes irrelevant to a mainline kernel.

That is convenient: a mainline `boot.img` is a self-contained experiment,
flashed with `fastboot flash boot`, and reverted by flashing the 5.4
`boot.img` back. Bootloader verification is already off
(`ro.boot.verifiedbootstate=orange`, vbmeta flags 3).
