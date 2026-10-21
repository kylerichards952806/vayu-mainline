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
| dtb | **none** (`dtb_size` 0); the tree travels in `dtbo` | the 5.4 kernel this device ships has `dtb_size` 0 and a one-entry DTBO table |
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

## Where the device tree goes

The board config says `BOARD_INCLUDE_DTB_IN_BOOTIMG := true`, but the 5.4 kernel
that actually runs on this phone is packaged the other way: its `boot.img` has
`dtb_size` 0 and its `dtbo.img` is a one-entry DTBO table holding the tree
(`ci/art22/kernel.zip` on the dev box, 54,437,904-byte kernel, 1,731,322-byte
LZ4 ramdisk, `os_version 0x220001aa`, no AVB footer, 56,176,640 bytes).

Boot and dtbo therefore have to agree: a `boot.img` with no DTB plus a blank
dtbo table would hand the kernel no device tree at all. Releases put the tree in
the DTBO table, exactly where the reference does, and `boot.img` stays DTB-free.

## The reference image's remaining fields

Measured from the boot image on the device, so a future change can be checked
against them instead of guessed:

| Field | Reference value |
| --- | --- |
| ramdisk | 1,731,405 bytes, **LZ4 legacy frame** (`02 21 4c 18`), i.e. `lz4 -l` |
| `id` | `9934e727ea251d55` |
| AVB footer | `AVBf` v1.0 in the last 64 bytes of the 128 MiB partition (the ROM's image is signed) |
| footer fields | `original_image_size` 56,971,264 = 0x3655000, `vbmeta_offset` 56,971,264, `vbmeta_size` 704 |
| vbmeta | `AVB0` struct at 56,971,264, then zeros to the footer |
| the 5.4 kernel's own packaging | unsigned and unpadded: 56,176,640 bytes, no `AVBf` |

The `dtbo` partition follows the same shape: a 291,611-byte table padded to
294,912 (72 pages), a 640-byte `AVB0` vbmeta there, and the footer at the end
of the 32 MiB partition. Our images are unsigned - see
[RELEASES.md](RELEASES.md#signing-and-the-avb-footer).

## What is still missing from the artifact

- **The ramdisk is our own, not Android's.** CI builds
  [initramfs/init.c](../initramfs/init.c) into an LZ4 legacy ramdisk and puts it
  in `boot.img`, so the artifact no longer depends on vendor bytes. It is a
  bringup init (mount pseudo filesystems, print identity, list pstore, idle as
  pid 1), not Android userspace; `--ramdisk-from-boot backup/boot-now.img`
  swaps in the device's own ramdisk instead when reaching Android is the goal.
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
