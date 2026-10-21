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

The board config says `BOARD_INCLUDE_DTB_IN_BOOTIMG := true`, and the 5.4 image
this phone boots (`uname -r 5.4.302-vayu-kyler084-0.0.20`) does exactly that:
`dtb_size` 791,273 in `boot.img`, plus a one-entry DTBO table in `dtbo.img`
holding the same tree. Releases mirror both, so a build can never hand the
kernel no tree at all.

An earlier reading of this repo took a *pulled boot image file* (56,176,640
bytes, `dtb_size` 0) for the partition's layout and concluded the device wants a
DTB-free `boot.img`. It does not: `boot` is a 128 MiB partition whose content is
an image, a vbmeta blob and a footer, and the pulled file was only the image
part of a different build.

## The reference image's remaining fields

Measured from the boot image on the device, so a future change can be checked
against them instead of guessed:

| Field | Reference value |
| --- | --- |
| ramdisk | 1,731,405 bytes, **LZ4 legacy frame** (`02 21 4c 18`), i.e. `lz4 -l` |
| `id` | `9934e727ea251d55` |
| AVB footer | `AVBf` v1.0 in the last 64 bytes of the 128 MiB partition |
| footer fields | `original_image_size` 56,971,264 = 0x3655000, `vbmeta_offset` 56,971,264, `vbmeta_size` 704 |
| vbmeta | `AVB0` struct at 56,971,264, **algorithm NONE**: no signature, no public key |
| boot descriptor | hash, partition `boot`, salt `4be8c0eb...375f`, sha256 over salt + image |

The `dtbo` partition has the same shape: the table and tree end at 294,912 (72
pages), a 640-byte `AVB0` vbmeta with algorithm NONE and salt
`358ae578...b088` follows, then zeros to the footer at the end of the 32 MiB
partition.

Reproducing the stock `boot` partition from its own 56,971,264-byte image, with
that salt and the recorded props, matches all 134,217,728 bytes except
avbtool's version string - so the parameters in
[configs/avb-vayu.json](../configs/avb-vayu.json) are the device's own, not
approximations. See [RELEASES.md](RELEASES.md#the-avb-footer).

## What the phone does with these images (measured 2026-10-21)

Every line is one flash followed by `fastboot reboot`, timing when the device
reappeared. "back in fastboot" means USB came back at about four seconds;
"ran" means it stayed configured but never enumerated as adb or fastboot.

| boot.img | dtbo.img | result |
| --- | --- | --- |
| released mainline (no AVB footer) | our one-entry table | back in fastboot |
| released mainline (AVB footer) | our one-entry table | back in fastboot |
| released mainline | blank table (0 entries) | back in fastboot |
| released mainline | no-op overlay, no board-id | back in fastboot |
| released mainline | no-op overlay + `qcom,board-id = <0x2f>` | back in fastboot |
| released mainline | the vendor's 291,547-byte overlay | back in fastboot |
| 5.4 kernel + 5.4 ramdisk + 5.4 DTB (repacked here) | **vendor overlay** | runs (Android/recovery in ~15s) |
| 5.4 kernel + 5.4 ramdisk + 5.4 DTB | our one-entry table | back in fastboot |
| 5.4 kernel + 5.4 ramdisk + 5.4 DTB | blank table | back in fastboot |
| **mainline kernel** + 5.4 ramdisk + **5.4 DTB** | vendor overlay | **stuck at the POCO logo: the kernel is running** |
| mainline kernel + our initramfs + our DTB | vendor overlay | back in fastboot |

What those rows say, in order of confidence:

1. **The mainline kernel does run on this phone.** With the 5.4 boot DTB and the
   vendor dtbo, the bootloader hands over and the phone sits at the logo with no
   USB device - a kernel with no console and no init it can use. It never got
   that far with our own DTB.
2. **ABL requires the vendor dtbo overlay.** Our table format is right: wrapping
   the vendor's own entry in our table boots, byte-identical to stock apart from
   avbtool's version string. Changing only the entry content - to our tree, to
   an empty overlay, to a board-id stub - always ends in fastboot. So the entry
   has to be an overlay ABL can apply, and it targets the vendor DT's nodes.
3. **Our own DTB is not yet accepted in that slot.** The vendor overlay cannot
   apply onto a mainline tree, and every combination with our DTB returned to
   fastboot within ~4 s. The failure has no USB or pstore trace: nothing was
   captured because the kernel never reached a console.

So the open work is the device-tree handoff, not the kernel image or the AVB
footer. The next experiments are to give the vendor overlay a base it can apply
to (keep the vendor DTB in `boot.img` and see how far the mainline kernel gets),
and to build a dtbo whose fragments target nodes that exist in our tree.

## What is still missing from the artifact

- **The ramdisk is our own, not Android's.** CI builds
  [initramfs/init.c](../initramfs/init.c) into an LZ4 legacy ramdisk and puts it
  in `boot.img`, so the artifact no longer depends on vendor bytes. It is a
  bringup init (mount pseudo filesystems, print identity, list pstore, idle as
  pid 1), not Android userspace; `--ramdisk-from-boot backup/boot-now.img`
  swaps in the device's own ramdisk instead when reaching Android is the goal.
- **No signature.** The footer is there, but its vbmeta uses algorithm NONE, so
  the digest is not authenticated: it proves the image is intact, not who built
  it. That is the same scheme the device's own partitions use, and it is the
  only one available without Xiaomi's key.
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
