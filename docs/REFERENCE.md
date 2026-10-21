# Reference sources for vayu

This kernel targets **LineageOS 24.0 / Android 17** on vayu — the same userspace
and vendor image the device runs today — on an ACK `android17-6.18` kernel.
Three trees are used as references. None of them can be built here; they are
consulted for facts.

## 1. LineageOS 24.0's 5.4 kernel — the primary reference

The kernel the device actually boots (`5.4.302-qgki_aman`), mirrored locally at
`mirrors/android_kernel_xiaomi_sm8150.git`, branch `MI_SM8150_5.4`.

This is the authority for *what the hardware is*, because it is the tree the
board actually runs:

| Path | Why it matters |
| --- | --- |
| `arch/arm64/boot/dts/xiaomi/vayu/vayu-sm8150.dtsi` | Reserved-memory map, regulators, PMIC wiring, UFS, USB, WCN3990 |
| `.../vayu/display/dsi-panel-j20s-42-02-0b-lcd-dsc-vid.dtsi` | The exact panel: timings, DSC, backlight, reset. Matches `androidboot` `dsi_j20s_42_02_0b_video_display` on the device |
| `.../vayu/vayu-pinctrl.dtsi` | Every pin state, including touch reset/irq |
| `.../vayu/vayu-audio-overlay.dtsi` | MI2S/TDM links, codec wiring, mic paths |
| `.../vayu/battery/fg-gen4-batterydata-*.dtsi` | Fuel-gauge profile for the 5160 mAh pack |
| `.../vayu/vayu-sm8150-camera-sensor-mtp.dtsi` | Sensor/lens topology (reference only — see below) |
| `vendor/sm8150-qgki_defconfig`, `vendor/xiaomi/sm8150-common.config`, `vendor/xiaomi/vayu.config` | The config chain that produces `CONFIG_LOCALVERSION="-qgki_aman"` |

What it **cannot** give you: any DTB that a 6.18 kernel can consume. Its bindings
are SDE/KGSL/techpack-specific (`qcom,sde-*`, `qcom,kgsl-*`, `qcom,msm-cam-*`),
so the board file has to be re-expressed against mainline bindings — which is
what `import/dts/` starts from.

## 2. Stock vendor kernel — `LuffyTaro008/android_kernel_xiaomi_vayu`

`https://github.com/LuffyTaro008/android_kernel_xiaomi_vayu`

The OEM-lineage tree for this device. Useful for:

* confirming what the vendor DTS *actually* configures where the LineageOS port
  already patched it (diffs against the stock branch show which quirks are
  LineageOS additions and which are Xiaomi's),
* panel/touch variants across `vayu` SKUs (the `dsi-panel-j20s-*` family has
  several revisions; the SKU on this device is `42_02_0b`),
* regulator currents and LDO assignments that mainline DTS often gets wrong,
* the `gpu`/`kgsl` and `wlan`/`icnss` bring-up order, which tells you what
  firmware blobs and calibration files the hardware expects.

Treat it as documentation, not as a source of portable code: it is a 5.4
downstream tree with the same techpack/KGSL/SDE stack as the LineageOS one.

## 3. postmarketOS SM8150 tree — the mainline-fact source

`https://gitlab.com/sm8150-mainline/linux` (pinned commit in
[PROVENANCE.md](PROVENANCE.md)), plus `sm8150-linux-mainline/pmaports`.

This is where `import/dts/sm8150-xiaomi-vayu.dts` came from: a real mainline
port of the same board, already expressed in upstream bindings. It is the only
one of the three that produces a DTB a 6.18 kernel can parse. Its userspace
assumptions (pmOS, Phosh, no Android HALs) are **not** what this repo targets —
only its device tree and its driver-level knowledge are reused.

## What is deliberately not reused

* **Firmware and calibration** (`firmware-xiaomi-vayu-*`, `adsp.mbn`, `modem.mbn`,
  `a640_zap.mdt`, WCN3990 `crnv21.bin`): proprietary, extracted from the device's
  own partitions, never committed.
* **Vendor HALs' kernel interfaces** (KGSL ioctls, SDE, techpack audio/camera,
  qcacld): a mainline kernel does not implement them, so the Android side has to
  move to open interfaces (DRM/KMS + minigbm, ASoC + UCM, ath10k, V4L2) — see
  [ASSESSMENT.md](ASSESSMENT.md) §1.
