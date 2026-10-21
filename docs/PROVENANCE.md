# Provenance of imported files

Everything below is GPL-2.0-only kernel/device source, imported unmodified so
that later commits diff against it cleanly.

## `import/dts/sm8150-xiaomi-vayu.dts`

| | |
| --- | --- |
| Upstream | `https://gitlab.com/sm8150-mainline/linux` |
| Commit | `93f303701cafa17135d8ee563ffdc39f319783f1` |
| Path | `arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dts` |
| Size | 106,466 bytes, 899 lines |
| Licence | `SPDX-License-Identifier: GPL-2.0` |
| Author | Copyright (c) 2023, Arseniy Velikanov `<adomerlee@gmail.com>` |
| Consumed by | postmarketOS `linux-postmarketos-qcom-sm8150` (pinned to that commit) |

It `#include`s `sm8150.dtsi`, `pm8150.dtsi`, `pm8150b.dtsi`, `pm8150l.dtsi`,
all of which exist in `android17-6.18` and in current mainline — verified by
fetching them from `android.googlesource.com`.

### `kernel/arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dts` (working copy)

A copy of the file above that is allowed to diverge, integrated into the
vendored kernel tree and registered in that directory's `Makefile`. Diff it
against the snapshot to see every rebase change:

```bash
diff -u import/dts/sm8150-xiaomi-vayu.dts \
  kernel/arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dts
```

Changes so far (6.18 rebase):

* re-add the Bluetooth GENI UART as `uart13: serial@c8c000` under
  `&qupv3_id_2`, plus its `qup_uart13_default` pinctrl state. Current
  `sm8150.dtsi` keeps only the GENI nodes its own boards use (`uart2`,
  `uart9`), so `&uart13` no longer resolves. Register, clock
  (`GCC_QUPV3_WRAP2_S3_CLK`), interrupt (SPI 585) and pin function (`qup13`) are
taken unchanged from the 6.4-era `sm8150.dtsi`.

## `kernel/` — vendored Android Common Kernel

| | |
| --- | --- |
| Upstream | `https://android.googlesource.com/kernel/common` |
| Branch | `android17-6.18` |
| Commit | `17e0d6827c4bf05f920cdc8fa92345da202da839` (2026-10-20) |
| Version | Linux **6.18.32** |
| Method | `git clone --depth 1 --single-branch` then `.git` removed |
| Size | 91,828 files, **283.92 MiB** in one pack, 1.3 GB checked out |
| Licence | GPL-2.0-only |

No history is vendored: one commit's worth of tree, so there is nothing to
rebase with `git`. Moving to a new ACK point means re-cloning the same way,
replacing `kernel/`, re-applying the vayu DTS, and updating `kernel.lock` in the
same commit.

Deliberately missing from the tree: `.git`, build output, and any firmware.

**Integrity check.** Every blob in `kernel/` was compared against upstream
`17e0d6827`: all 91,828 paths are byte-identical (same blob SHA), with exactly
two intended deltas — `arch/arm64/boot/dts/qcom/Makefile` (one added `dtb-y`
line) and the new `sm8150-xiaomi-vayu.dts`.

### 13 filenames a Windows checkout cannot hold

The tree was cloned on NTFS, which is case-insensitive, so upstream paths that
differ from a sibling only by case were collapsed. They were written back into
the git index from the upstream blobs (so the repository has them and a Linux
checkout materialises all of them), but this working tree cannot show both:

```
include/uapi/linux/netfilter/xt_CONNMARK.h      include/uapi/linux/netfilter/xt_DSCP.h
include/uapi/linux/netfilter/xt_MARK.h          include/uapi/linux/netfilter/xt_RATEEST.h
include/uapi/linux/netfilter/xt_TCPMSS.h        include/uapi/linux/netfilter_ipv4/ipt_ECN.h
include/uapi/linux/netfilter_ipv4/ipt_TTL.h     include/uapi/linux/netfilter_ipv6/ip6t_HL.h
net/netfilter/xt_DSCP.c                         net/netfilter/xt_HL.c
net/netfilter/xt_RATEEST.c                      net/netfilter/xt_TCPMSS.c
tools/memory-model/litmus-tests/Z6.0+pooncelock+poonceLock+pombonce.litmus
```

Those 13 paths are marked `skip-worktree` locally so `git status` stays clean on
Windows; they are present in the commit and in CI. Any future re-import on
Windows needs the same step — plain `git add` also silently drops every `*.S`
file, because the kernel's own `.gitignore` has `*.s` and NTFS folds the case.

## `import/config/config-postmarketos-qcom-sm8150.aarch64`

| | |
| --- | --- |
| Upstream | `https://github.com/sm8150-linux-mainline/pmaports`, branch `master` |
| Path | `device/testing/linux-postmarketos-qcom-sm8150/config-postmarketos-qcom-sm8150.aarch64` |
| Size | 228,016 bytes, 7,968 lines |
| Licence | GPL-2.0-only (kernel configuration) |

Useful anchors in it: `CONFIG_ATH10K_SNOC=m`, `CONFIG_QCOM_IPA=y`,
`CONFIG_QCOM_FASTRPC=y`, `CONFIG_ARM64=y`, `CONFIG_MODULES=y`.

## Not imported (deliberately)

* **Firmware** (`firmware-xiaomi-vayu-*`): proprietary, must be extracted from
  the device's own `vendor`/`modem` partitions and never committed here.
* **`lineage_mainline_common`**: only relevant at phase P9; pulling it in now
  would add an Android tree to a project that has not booted yet.
* **The 5.4 vendor tree**: it already lives at
  `android_kernel_xiaomi_sm8150` (`MI_SM8150_5.4`) and is not modified by this
  repo. Nothing here replaces the working ROM.

## Licence

This repository is **GPL-2.0-only**, inherited from the imported kernel source.
