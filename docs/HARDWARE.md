# Hardware matrix - vayu on a mainline kernel

Legend: **up** = supported in `torvalds/linux` for SM8150; **vayu** = what the
board additionally needs, and whether the imported postmarketOS DTS already
carries it; **blocker** = what stops it working today.

| Subsystem | SoC driver in mainline | vayu-specific work | Status | Blocker |
| --- | --- | --- | --- | --- |
| Clocks (GCC, RPMh) | `clk/qcom/gcc-sm8150.c`, `rpmh` | none | up | - |
| Display clocks | shared display-clock driver (no `dispcc-sm8150.c`; SM8150 rides the common path) | none | up | - |
| CAMCC / VIDEOCC | `camcc-sm8150.c`, `videocc-sm8150.c` | none | up (clocks only) | camera/video still need the rest of the pipeline |
| Pinctrl | `pinctrl-msm` + `pinctrl-sm8150` | 200+ pin states, in the imported DTS | up | - |
| Interconnect | `qnoc-sm8150` | node + bandwidth votes | up | - |
| Regulators | `rpmh-regulator` | PM8150/8150B/8150L rails, in DTS | up | - |
| Display | **DPU 5.0 SM8150 catalog** (`dpu_5_0_sm8150.h`, since ~6.3) + DSI | panel driver + backlight + `mdss` node | partial | vayu's panel (1080x2400, `dsi_j20s_*`) has no mainline driver; the pmOS fork carries one |
| GPU | `a6xx` - a640 (`chip_ids 0x06040001`, `a640_gmu.bin`, `a640_zap.mdt`) | zap/gmu firmware from vendor partition | partial | firmware extraction + Mesa only |
| Touchscreen | generic `goodix`/`focaltech` | correct compatible + reset/irq pins | partial | which controller this SKU has; DTS already picks one |
| Keys / haptics | `gpio-keys`, `pm8xxx-vibrator` | in DTS | up | - |
| Storage | UFS host + QMP UFS PHY | vayu's reserved-memory carve-outs (DTS rewrites all of them) | up | - |
| USB | DWC3 + QMP PHY | `usb@a600000` role switch | up | - |
| PCIe | QMP + DesignWare | none used by the phone | up | - |
| Wi-Fi | **`ath10k_snoc`** (`qcom,wcn3990`) - *not* qcacld/icnss | `wifi@c800000` node + firmware | partial | firmware path via `pd-mapper`/`rmtfs`; Android's `WifiService` needs a HAL, not the vendor `qcacld` stack |
| Bluetooth | `qca` serdev (WCN3990) | `bluetooth` node + `qca,bt` firmware | partial | same firmware path |
| Audio (DSP) | `q6apm`/`q6afe`/`q6prm` + WCD9340 | topologies, machine driver, UCM | partial | no SM8150 phone audio configuration is known-good upstream; pmOS has UCM profiles |
| Sensors | `ssc`/`iio` (SLPI) | SLPI remoteproc + sensor drivers | partial | sensor blobs are vendor-specific |
| Modem (voice) | `remoteproc` MPSS + `msm-modem` userspace | `mpss` node, `qcom,smem` | partial | needs `tqftpserv`, `pd-mapper` |
| Modem (data) | IPA + `rmnet` | IPA node, GSI | unproven | no known-good SM8150 mobile-data setup on mainline |
| Camera | **none** - `camss.c` has zero SM8150 support | whole CAMSS port + sensors | **missing** | out of scope (months) |
| Video (Venus) | `venus` V4L2 (sm8250-era) | firmware + node | partial | decode/encode unverified on SM8150 |

## The decisive contrast with the current ROM

The 5.4 kernel the phone runs today exposes a completely different set of
interfaces, and the vendor image is written against them:

| Feature | 5.4 vendor kernel (what the ROM uses) | mainline |
| --- | --- | --- |
| GPU | `/dev/kgsl-3d0` ioctls (KGSL) | DRM/MSM + freedreno |
| Display | SDE DRM-private ioctls, `dtbo` overlay | DPU 5.0 KMS, panel driver |
| Audio | `/dev/msm_pcm*`, APR, techpack machine drivers | ASoC + `q6apm`, UCM |
| Camera | `techpack/camera` + `/dev/video*` | nothing for SM8150 |
| Wi-Fi | `qcacld-3.0` + `icnss` | `ath10k_snoc` |
| Buffers | ION-era heaps | DMA-BUF heaps |
| Modules | none - everything built in | modules expected |

That table is the whole answer to "can I keep the ROM and swap the kernel": no.
