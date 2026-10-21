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
