# Releases

Every kernel release is a GitHub release whose asset is a TWRP-flashable zip
that writes **both** `boot` and `dtbo`.

## Naming

```
<kernel version>-<builder>-<device>-<date>.zip
6.18.32-kyler084-vayu-2026-10-21.zip
```

| Field | Where it comes from |
| --- | --- |
| kernel version | first field of `include/config/kernel.release` (`6.18.32`) |
| builder | the builder part of `CONFIG_LOCALVERSION="-vayu-kyler084"`, so the file name cannot drift from the name Settings shows |
| device | `vayu` |
| date | build date, UTC, `YYYY-MM-DD` |

The release tag is the same string without `.zip`. Releases are published by
`.github/workflows/build.yml` when it runs with `release: true`, or on a `v*`
tag push, and only after the build, the kernel-name assertion and the zip
verification have all passed.

## What is inside the zip

```
META-INF/com/google/android/update-binary   shell installer for TWRP
META-INF/com/google/android/updater-script  #MAGIC, flashing is done by update-binary
boot.img                                    header v2, kernel + DTB (+ ramdisk)
dtbo.img                                    valid DTBO table, 32 MiB partition
```

`update-binary` resolves `/dev/block/bootdevice/by-name` (falling back to
`/dev/block/by-name`), writes each image with `dd`, then reads the partition
back and compares it with the file, so a short write or a read-only partition
fails the install instead of reporting success.

## dtbo policy

The zip always flashes `dtbo.img`, because leaving a vendor overlay set in place
under a mainline kernel is how a port ends up with no display. What it writes is
a **valid DTBO table with zero entries**, not a block of zeros: the vendor image
on this device is a proper table (32-byte header, one entry, one 291 KB base DTB
at id 0, rev 0), and a table with no entries is the same structure with nothing
to apply. `scripts/mkdtbo.py` writes it and verifies it.

`--dtb` on `mkdtbo.py build` embeds trees the way the vendor image does, and
`mkrelease.py build --dtbo FILE` flashes a real image instead, for anyone who
wants the vendor overlays back.

## Signing and the AVB footer

The released images are **unsigned**: there is no AVB footer and no vbmeta.
The reference images on the device carry one - `boot-now.img` has a 704-byte
`AVB0` vbmeta at offset 56,971,264 and an `AVBf` footer in the last 64 bytes of
the 128 MiB partition; `device/dtbo.img` has a 640-byte vbmeta at 294,912 and
its footer at the end of its 32 MiB partition - and both are signed with keys
this repo does not have and cannot derive.

Writing a footer signed by anything else would be worse than writing none: a
bootloader that finds a footer will verify it, while an image without one is
accepted when verification is disabled. Flashing therefore needs an unlocked
bootloader, which TWRP implies anyway. If the vendor key ever becomes
available, `mkbootimg.py`/`mkrelease.py` can gain an `avbtool` step and the
layout above is the one to reproduce.

## Ramdisk

Releases carry **our own ramdisk**: CI cross-compiles
[initramfs/init.c](../initramfs/init.c) to a static aarch64 binary and packs it
with `scripts/mkinitramfs.py --lz4`, the same container the stock image uses.
It mounts the pseudo filesystems, prints `uname` and the cmdline, lists
`/sys/fs/pstore`, and idles as pid 1 - enough to complete a boot and to recover
a log on a device with no UART, with no vendor bytes involved.

The device's stock ramdisk is an LZ4 legacy frame of 1,731,405 bytes, and
`mkbootimg.py --ramdisk-from-boot backup/boot-now.img` copies exactly that
payload instead, when the goal is to reach Android userspace:

```bash
python3 scripts/mkbootimg.py build \
    --kernel arch/arm64/boot/Image \
    --dtb arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dtb \
    --ramdisk-from-boot backup/boot-now.img \
    --partition-size 0x8000000 -o boot.img
python3 scripts/mkrelease.py build --boot boot.img --version 6.18.32 \
    --builder kyler084 --device vayu --date 2026-10-21 -o release.zip
```

`mkbootimg.py verify` reports which compression it found, so a gzip ramdisk
slipping in where the device expects LZ4 is visible rather than silent.
