# Build configs

Two files, both used by CI:

| File | Role |
| --- | --- |
| `vayu-android17.config` | The LineageOS 24.0 5.4 config, filtered to symbols the vendored 6.18 tree still defines. Generated - do not hand-edit. |
| `vayu-mainline.fragment` | Hand-written overlay that enables the upstream drivers the vendor config never needed. |
| `vayu-android17.dropped` | Every source symbol the 6.18 tree no longer defines. Kept for review, not used by the build. |

## Generation

The source is the config chain LineageOS 24.0 actually boots on this device  - 
`vendor/sm8150-qgki_defconfig` + `vendor/xiaomi/sm8150-common.config` +
`vendor/xiaomi/vayu.config`, i.e. the running kernel's `.config` (kept as
`stock.config` on the dev box). It is filtered, not rewritten:

```bash
./scripts/gen-config.py ../stock.config kernel \
    configs/vayu-android17.config \
    --dropped configs/vayu-android17.dropped \
    --fragment configs/vayu-mainline.fragment
```

Current result:

```
source symbols : 5276
kept           : 4434
```

`kept` is the filtered source plus the fragment's entries plus the overrides,
so it moves whenever the fragment does; the meaningful number is `dropped`.

The 854 dropped symbols are the 5.4-only generation: Ion, KGSL, SDE, the
techpack audio/camera/video plumbing, qcacld/icnss, and assorted 5.4 options.
They are listed in `vayu-android17.dropped` rather than silently dropped,
because that list is the clearest measure of how much of the vendor config has
no 6.18 counterpart.

Symbols whose value kconfig recomputes (`CONFIG_CC_VERSION_TEXT`,
`CONFIG_CLANG_VERSION`, ...) are stripped so the file does not claim a toolchain
the build does not use.

One override: `CONFIG_LOCALVERSION="-vayu-kyler084"` (and `LOCALVERSION_AUTO` off, so
nothing is appended). Android shows this string under Settings > About phone >
Kernel version, because that page reports `uname -r`, which is
`6.18.32-vayu-kyler084` here. CI does not take that on trust: the **Build Image**
step asserts `include/config/kernel.release` and then searches the linked
`Image` for `-vayu-kyler084`.

## Why a fragment on top

A faithful filter of the vendor config is not a bootable mainline config. The
vendor stack reaches storage, display and Wi-Fi through `SCSI_UFS_QCOM`-era
vendor drivers, `techpack/display` (SDE) and `qcacld`, so the filtered file has
`# CONFIG_DRM_MSM is not set`, no `ATH10K_SNOC`, and no `SCSI_UFS_QCOM` - those
symbols either did not exist or were not needed on 5.4. Layering
`vayu-mainline.fragment` turns the upstream equivalents on (DRM/MSM, MSM UFS,
ath10k_snoc, Q6V5 remoteproc, GENI serial, RPMh clocks/regulators, interconnect,
dmabuf heaps, binder). Every symbol in it is validated against the target
Kconfig by the generator, so a typo fails generation rather than silently
becoming a no-op. The fragment can switch symbols off too, with
`# CONFIG_FOO is not set`.

Two entries are there because this ACK tree does not compile without them:

- `CONFIG_F2FS_UNFAIR_RWSEM=y` - `fs/f2fs/f2fs.h` uses `sem->read_waiters`
  unconditionally in `f2fs_down_read()` but only declares the member under this
  symbol, so f2fs fails to build when it is unset.
- `# CONFIG_GKI_HACKS_TO_FIX is not set` - it exists so vendor *modules* can be
  built in a separate tree. It selects `GKI_HIDDEN_DRM_CONFIGS`, which selects
  `HMM_MIRROR` but not `MMU_NOTIFIER`, and ACK's `mm/hmm.c` calls
  `mmu_interval_check_retry()` outside any `#ifdef`, so the kernel does not
  compile. Nothing here is an out-of-tree module: in-tree drivers select their
  own hidden dependencies. `MMU_NOTIFIER` itself is a hidden bool and cannot be
  set from `.config`, which is why the gate has to go rather than be satisfied.

## CI builds without debug information

`CONFIG_DEBUG_INFO=y` (DWARF4) is kept in `vayu-android17.config` because a
vayu has no UART: symbols in `vmlinux` are how a panic is read out of ramoops.
CI turns it off before `olddefconfig`, because linking `vmlinux.o` with it
peaks at 15.9 GB on the 16 GB hosted runner and the job is killed. Debug info
does not affect code generation, so the `Image` CI verifies is byte-for-byte
the one a full build produces - only `vmlinux` differs.

## CI assertions

`.github/workflows/build.yml` copies `vayu-android17.config` (fragment already
baked in by the generator) into the out-of-tree build directory, runs
`olddefconfig`, and then **fails** if any of the required symbols did not survive
dependent-symbol resolution - the list is in the workflow's "Verify config"
step (ARM64, ARCH_QCOM, PINCTRL_SM8150, QCOM_CLK_RPMH,
INTERCONNECT_QCOM_SM8150, DRM_MSM, SCSI_UFS_QCOM, PHY_QCOM_QMP_UFS, USB_DWC3,
ATH10K_SNOC, QCOM_Q6V5_PAS, SERIAL_QCOM_GENI, F2FS_UNFAIR_RWSEM, and the
localversion string), and if `GKI_HACKS_TO_FIX` or `HMM_MIRROR` is on.

That check exists because `olddefconfig` is allowed to drop anything whose
dependencies are unmet; without it, a config that looks right could build a
kernel with no display or no storage and still report success.
