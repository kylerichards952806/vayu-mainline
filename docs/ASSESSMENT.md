# Assessment: moving vayu from the 5.4 vendor kernel to "mainline-android"

Date: 2026-10-21
Device: POCO X3 Pro (`vayu`), SM8150, bootloader unlocked, LineageOS 24.0
(Android 17) on a **5.4.302-qgki_aman** downstream kernel with `techpack/*`,
`qcacld-3.0`, `icnss`, KGSL and SDE display.

---

## 0. The question contains two different projects

"Bring vayu to mainline-android" can mean one of these. They differ by roughly
two orders of magnitude in effort, so the plan has to pick one.

| # | Interpretation | Verdict |
| --- | --- | --- |
| **A** | Replace the 5.4 **vendor** kernel with a newer **vendor** kernel (ACK 6.18 rebased with Qualcomm's SM8150 board support) so the existing Android 17 ROM + vendor blobs keep working. | **Not feasible.** No such base exists, and the vendor userspace is ABI-locked to the 5.4 drivers. |
| **B** | True upstream bringup: run a **mainline/ACK kernel with an open userspace** (postmarketOS today, optionally `lineage_mainline_common` later). Camera / cellular degrade or disappear. | **Feasible, and someone already did the hard 60%.** Weeks-to-months, not years. |
| **C** | `android-mainline` (the branch itself) as a device kernel. | **Do not.** It tracks Linux **7.3-rc** development, deliberately reports a fake `7.2-rc9` for userspace compatibility, and carries **no KMI stability guarantee**. It is not a device kernel. The device-facing branch for Android 17 is `android17-6.18`. |

Everything below assumes **B**, with `android17-6.18` as the Android-side target
(and plain 6.18 LTS for a Linux userspace), because that is the only version of
this task that terminates.

---

## 1. Why A is a dead end (the part that is easy to underestimate)

A normal "kernel bump" for a Qualcomm phone means: start from the next CAF
release for that SoC, keep the board files, re-port the downstream drivers that
changed APIs, rebuild modules. That path requires a next CAF release to exist.

For SM8150 it does not, in any usable form:

* Qualcomm's public SM8150 lineage (`LA.UM.9.1.r1-*`, the base of Xiaomi's
  `vayu-r-oss`) is a **5.4** tree. There is no `SM8150` + `techpack/` + KGSL +
  qcacld BSP on 5.10/5.15/6.1 that a maintainer could rebase onto.
* The downstream stack is enormous and not upstream-adjacent:
  `techpack/display` (SDE), `techpack/audio` (APR/q6 + ASoC machine drivers),
  `techpack/camera` (+ `camera-kernel`), `video-driver` (Venus), `msm/kgsl`
  (Adreno), `qcacld-3.0` + `icnss` (WLAN). Each is a kernel-internal-API port of
  tens to hundreds of thousands of lines, every time the kernel moves a major
  version — and none of it exists in ACK.
* Even if it compiled, the **vendor image is what pins you to 5.4**. The blobs in
  `vendor/` speak to the kernel through private interfaces:
  `/dev/kgsl-3d0` ioctls (gralloc, Adreno), SDE DRM-private ioctls (HWC),
  `/dev/msm_pcm*` + APR (audio HAL), `/dev/video*` msm-camera (camera provider),
  `/dev/ion`-era heap assumptions (older gralloc), qcacld netlink/WMI (WLAN HAL),
  rmnet/IPA data path (RIL). Keeping the HAL *interfaces* does not keep the
  driver ABIs underneath them.
* Also: this ROM's 5.4 kernel has **no loadable modules at all** (`lsmod` is
  empty; everything is built in), so there is not even a module set to
  re-target. `vendor_dlkm` contains nothing for us.

**Effort for A: unbounded.** It is not a kernel port, it is writing a new
downstream BSP plus a new vendor HAL stack for a 2019 SoC. Estimate: 1–2
person-years to reach feature parity, with no upstream to land it in.

That is the honest answer to "how hard would it be to put a mainline-android
kernel under the *existing* ROM": you would get a black screen and a boot loop,
because `init` and every display/audio/graphics HAL would find none of their
device nodes.

---

## 2. Why B is tractable (what already exists)

The postmarketOS SM8150 effort has already produced, for this exact phone:

* `sm8150-xiaomi-vayu.dts` — 899 lines, imported into this repo. It carries the
  panel, touchscreen, PMIC/regulator tree, UFS, USB, WCN3990, gpio-keys and the
  device's reserved-memory layout (which differs from the reference board and is
  the classic source of "mainline boots then dies on UFS" bugs).
* a 7,968-line kernel config (`import/config/`), plus UCM audio profiles,
  firmware packaging (`firmware-xiaomi-vayu-{adreno,adsp,cdsp,wlan,modem,ath10k,
  touchscreen}`) and `msm-modem` / `pd-mapper` / `tqftpserv` userspace.
* `deviceinfo` values that already solve vayu's boot-image quirks (header v2,
  `append_dtb=true`, kernel offset `0x8000`, ramdisk `0x01000000`, 4096 pages).

And SM8150 itself is well supported upstream, which is the other half:

| Piece | Upstream |
| --- | --- |
| GCC / RPMh / pinctrl / interconnect | `gcc-sm8150`, `qnoc-sm8150`, `pinctrl-sm8150` — present |
| Display | DRM MSM **DPU 5.0 SM8150 catalog** (`dpu_5_0_sm8150.h`) + DSI — present since ~6.3 |
| GPU | Adreno **a640** in the `a6xx` catalog (`a640_hwcg`, `a640_gbif`) — present |
| Storage / USB / PCIe | UFS + QMP PHY, DWC3 + QMP — present |
| WLAN | `ath10k_snoc` (WCN3990), *not* qcacld/icnss |
| Audio | `q6afe`/`q6apm`, WCD9340 DTSI — present as components |
| Camera | CAMSS has **no SM8150 support** |
| Modem data | IPA + rmnet exist; an SM8150 phone data path is unproven |

Note that display+GPU present upstream is exactly why "mainline boots and shows
a picture" is realistic, and why camera/modem are the parts that are not.

---

## 3. Effort, phase by phase

Estimates assume one experienced person, working from the imported DTS, with CI
as the build loop. "Focused" = full-time equivalent.

| Phase | Goal | Work | Estimate | Confidence |
| --- | --- | --- | --- | --- |
| **P0** | Decide target + baseline | this document | done | — |
| **P1** | DTB compiles on 6.18 | Rebase 6.4-era DTS over 6.18 `sm8150.dtsi`/`pm8150*.dtsi`: renamed bindings, removed properties, new `#include`s. CI here does exactly this. | **2–5 days** | high |
| **P2** | Boots to initramfs | Reserved-memory map, RPMh regulators, UFS, SMEM/`qcom,smem`, USB gadget console. This is where "no console output at all" gets debugged — vayu has no exposed UART, so USB `earlycon`/ramoops is the only window. | **1–2 weeks** | medium-high |
| **P3** | Display + touch + keys | DPU 5.0 pipeline, DSI panel driver (the panel is board-specific; the pmOS tree has it), backlight, `goodix`/`focaltech` touch, gpio-keys. | **1–3 weeks** | medium |
| **P4** | GPU | a640 + `a630_sqe.fw`/`a630_gmu.bin`/`a640` zap firmware from the vendor partition, Mesa/freedreno. | **3–7 days** | high |
| **P5** | Wi-Fi + BT | `ath10k_snoc` + WCN3990 firmware, `qca` Bluetooth serdev, `pd-mapper`/`rmtfs` for the remoteproc firmware path. | **1–2 weeks** | medium |
| **P6** | Audio | `q6apm`/`q6afe` topology + WCD9340 codec + machine driver + UCM (reuse `sm8150-linux-mainline/alsa-ucm-conf`). Historically the slowest DSP bringup. | **2–4 weeks** | low-medium |
| **P7** | Modem / calls / data | `msm-modem`, `tqftpserv`, IPA, `rmnet`. Calls may work; **mobile data is genuinely uncertain** on SM8150 upstream. | **2–6 weeks** | low |
| **P8** | Camera | No SM8150 CAMSS. Would be a from-scratch ISP/CSID/CSIPHY port + sensor drivers. | **3–6 months** | — (out of scope) |
| **P9** | Android on top (optional) | `lineage_mainline_common`: DRM hwcomposer, minigbm, Mesa, tinyalsa audio HAL, no RIL, no camera. A second project stacked on P1–P7. | **2–4 months** | low |

**Totals**

* "Mainline kernel boots, screen lights up, USB works": **≈ 3–6 weeks** focused.
* "Daily-drivable Linux phone (pmOS), minus camera and probably mobile data":
  **≈ 3–5 months** focused, spread over calendar time.
* "LineageOS 24 with a mainline kernel and working camera/RIL": **not this
  decade**, and not because of the kernel.

---

## 4. Difficulty scorecard

| Task | Difficulty | Why |
| --- | --- | --- |
| Boot *a* mainline kernel on vayu | **3/10** | DTS exists, SoC support is upstream, bootloader is unlocked, rollback is one `fastboot flash boot`. |
| Usable Linux phone (pmOS-class) | **7/10** | Audio/modemu are open-ended; display and touch are fiddly but known. |
| Android 17 + mainline kernel **with the current vendor blobs** | **10/10** | Not a kernel task. It requires a new downstream BSP *and* new HALs. |
| `android-mainline` as the device kernel | **n/a** | Wrong branch by design: dev tree, no KMI stability, reports a fake version. |

Blunt version: **"make vayu run mainline" — yes, weeks. "make the current ROM
run on mainline" — no.**

---

## 5. Recommended path

1. **Keep the 5.4 ROM exactly as it is.** It works; nothing in this repo
   replaces it. The mainline experiment lives in its own `boot.img`.
2. **Target `android17-6.18`** for anything Android-shaped (KMI generation
   matches Android 17), and plain **6.18 LTS** for a Linux/pmOS-style userspace.
   Do not chase `android-mainline`.
3. **P1 first, in CI**: make the imported DTS compile clean against 6.18. No
   hardware risk, immediate signal, and it is the precondition for everything.
4. **Then P2 with a minimal initramfs** and USB console before touching
   display/GPU — otherwise every later failure is unattributable.
5. **Reuse, don't rewrite**: port the pmOS DTS/config/firmware/UCM forward as
   the baseline, and send fixes upstream where they are generic
   (`sm8150.dtsi`, `pm8150*`, panel driver, `ath10k_snoc` quirks).
6. **Treat camera and mobile data as out of scope** until P1–P6 are done. They
   are where such projects die.

## 6. Risks

| Risk | Mitigation |
| --- | --- |
| No local toolchain (Windows box, no WSL, no `make`/clang) | CI builds everything; the workflow takes a `base` input so a base can be bisected. |
| 6.4-era DTS vs 6.18 bindings drift | P1 is exactly this; CI reports it per push. |
| No UART on retail vayu | Plan for USB `earlycon` + `pstore`/ramoops from the start. |
| Panel/touch drivers live only in the pmOS fork | Track them as patches in `patches/`, upstream what is generic. |
| Firmware is proprietary and lives on the vendor partition | Never redistribute; extract on-device, mirror the `firmware-xiaomi-vayu-*` split. |
| Scope creep toward "replace the ROM's kernel" | §1. Write it down; it is not a milestone. |
