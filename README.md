# vayu-mainline

Mainline / Android-Common-Kernel bringup work for the **Xiaomi POCO X3 Pro**
(`vayu` / `M2102J20SG`, Qualcomm **SM8150**), which currently runs a downstream
**5.4 QGKI** vendor kernel (`5.4.302-qgki_aman`, `techpack/*` + `qcacld-3.0`).

> **Target: LineageOS 24.0 (Android 17) on an ACK `android17-6.18` kernel.**
> The 5.4 LineageOS kernel the device runs today is the hardware reference; the
> vendor HAL stack has to move to open interfaces, which is the real work. See
> [docs/REFERENCE.md](docs/REFERENCE.md) for the three reference trees.
>
> **Status: source vendored, nothing boots yet.** The ACK tree is in `kernel/`,
> the board description compiles, no boot attempt has been made.

Read [docs/ASSESSMENT.md](docs/ASSESSMENT.md) first - it answers "how easy is
this?" with numbers, and separates the two very different projects that the
phrase *"move vayu to mainline-android"* can mean.

## What is in here

| Path | What it is |
| --- | --- |
| `kernel/` | **Vendored Android Common Kernel**, branch **`android17-6.18`**, commit `17e0d6827`, Linux **6.18.32**. Shallow: one tree, no history. 91,828 files, 284 MiB packed. See `kernel.lock`. |
| `kernel/arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dts` | The vayu device tree, integrated into the tree and registered in the qcom `Makefile`. |
| `import/dts/sm8150-xiaomi-vayu.dts` | The pristine postmarketOS original this was forked from - the rebase log is the diff against the in-tree file. |
| `configs/` | `vayu-android17.config` (LineageOS 24.0's 5.4 config filtered to 6.18 symbols), `vayu-mainline.fragment` (upstream drivers the vendor config never needed) and the dropped-symbol list. See its README. |
| `import/config/` | Reference configs only, not used by the build. |
| `.github/workflows/build.yml` | Builds `sm8150-xiaomi-vayu.dtb` (and optionally the full `Image`) out-of-tree with LLVM 18. |
| `docs/HARDWARE.md` | Per-subsystem status: what upstream already has for SM8150, what vayu needs on top, what is missing entirely. |
| `docs/REFERENCE.md` | The LineageOS 5.4 tree, the stock vendor tree and the postmarketOS port: what to take from each. |
| `docs/PROVENANCE.md` | Exact upstream commits, sizes, and licences. |

Everything under `kernel/` and `import/` is GPL-2.0-only kernel source; the repo
is GPL-2.0-only.

## Build

The tree is built **out-of-tree** so `kernel/` stays pristine and never fills
with build artifacts:

```bash
make -C kernel O=../build ARCH=arm64 LLVM=1 defconfig
kernel/scripts/kconfig/merge_config.sh -m -O ../build ../build/.config \
  import/config/config-postmarketos-qcom-sm8150.aarch64
make -C kernel O=../build ARCH=arm64 LLVM=1 olddefconfig

make -C kernel O=../build -j"$(nproc)" ARCH=arm64 LLVM=1 dtbs
make -C kernel O=../build -j"$(nproc)" ARCH=arm64 LLVM=1 Image   # full kernel
```

Requires `clang`/`ld.lld` (17 or newer), `bc`, `bison`, `flex`, `libssl-dev`,
`libelf-dev`. There is **no local toolchain on the Windows dev box** (no `make`,
no clang, no WSL - see the 5.4 tree's `AUDIT.md` section 5), so CI is the build path.

The build config is **not** `defconfig`: it is the LineageOS 24.0 config filtered
to what this tree still defines, plus a small upstream-driver fragment. CI
asserts the important symbols survive `olddefconfig` before compiling.

CI input: `full` (build the arm64 `Image` as well as the DTBs).

## Why this exact tree

`android17-6.18` is the ACK line for Android 17, so it is the branch that matches
the LineageOS 24 userspace generation. `android-mainline` is deliberately **not** used: it tracks Linux
7.3-rc, reports a fake `7.2-rc9` for userspace compatibility, and carries no KMI
stability guarantee.

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
