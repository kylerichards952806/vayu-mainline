# The boot image CI produces

`boot.img` for vayu is an Android **header v2** image: the device has no
`vendor_boot` partition, so kernel, ramdisk and DTBs all live in `boot`.
[scripts/mkbootimg.py](../scripts/mkbootimg.py) writes it and re-parses the
result; both run in CI, and the same script builds the artifact by hand.

## Layout

| Field | Value | Where it comes from |
| --- | --- | --- |
| magic | `ANDROID!` | format |
| header version | 2 | `BOARD_BOOT_HEADER_VERSION := 3` only when `TARGET_IS_VAB`; vayu is not VAB |
| header size | 1660 bytes | `boot_img_hdr_v2` |
| page size | 4096 | `BOARD_KERNEL_PAGESIZE` |
| kernel | `Image`, load `0x00008000` | `BOARD_KERNEL_IMAGE_NAME := Image`, base `0x00000000` |
| ramdisk | empty in CI, load `0x01000000` | see the ramdisk note below |
| dtb | `sm8150-xiaomi-vayu.dtb`, load `0x01f00000` | `BOARD_INCLUDE_DTB_IN_BOOTIMG := true` |
| tags address | `0x00000100` | `mkbootimg` default for base 0 |
| os_version | `0x220001aa` (Android 17, 2026-10) | matches the image on the device today |
| cmdline | the sm8150-common `BOARD_KERNEL_CMDLINE` plus vayu's two appended lines | official LineageOS trees |
| id | first 8 bytes of SHA-1 over each payload and its length | AOSP `mkbootimg` |

`recovery_dtbo` is written as zero-sized; vayu uses a separate 32 MiB `dtbo`
partition (`BOARD_KERNEL_SEPARATED_DTBO := true`).

## How the format was pinned down

Not from documentation: from the phone's own boot image (kept on the dev box as
`backup/boot-now.img`, outside this repo, since it carries vendor blobs). It is
128 MiB and AVB-signed, and parses as header v2 with page 4096, kernel at 0x8000,
ramdisk at 0x01000000, DTB at 0x01f00000 and `os_version 0x220001aa`. Feeding
its extracted kernel, ramdisk and DTB back through `mkbootimg.py build`
reproduces the device image **byte for byte** across the whole 56,971,264-byte
payload, including the `id` field (`9934e727ea251d55`). That reproduction is
what the packer's defaults are derived from; `verify` also accepts the device
image unchanged.

## What is still missing from the artifact

- **No ramdisk.** CI packages the kernel and DTB only, so `ramdisk_size` is 0.
  Android's `init` lives in the ramdisk; until the P2 initramfs exists, this
  image is a layout-correct kernel carrier, not a bootable Android boot image.
  `--ramdisk FILE` fills the slot when that work lands.
- **No AVB footer.** The device image ends with an `AVBf` vbmeta struct; ours
  does not. A bootloader with verification enforcing will reject it, so flashing
  this needs an unlocked bootloader, or a later step that runs `avbtool` with the
  vayu keys - which is why this repo does not sign.
- **No bootconfig.** Header v2 devices read the cmdline from the header field
  (`cmdline`/`extra_cmdline`), not from a bootconfig section, which is why the
  device cmdline is baked in rather than appended by the build.

## Using it

```bash
python3 scripts/mkbootimg.py build --kernel arch/arm64/boot/Image \
    --dtb arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dtb -o vayu-boot.img
python3 scripts/mkbootimg.py verify --image vayu-boot.img \
    --expect-kernel arch/arm64/boot/Image \
    --expect-dtb arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dtb \
    --expect-model "Xiaomi POCO X3 Pro"
```

`verify` exits non-zero on any failed check; `--kernel-release` additionally
asserts that the kernel carries the name Settings will show.
