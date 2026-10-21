# Minimal initramfs

One static aarch64 binary, `/init`, is the whole userspace. It exists so a
release image does not have to borrow the vendor ramdisk to be complete, and so
a first mainline boot can say something about itself on a device with no UART.

## What init does

1. Mounts `proc`, `sysfs`, `devtmpfs`, `devpts`, `tmpfs` on `/tmp`, and `pstore`.
2. Prints `sysname release machine` and the head of `/proc/cmdline`.
3. Lists `/sys/fs/pstore`, which is where a ramoops record from the previous
   boot survives a reset. On this device that listing is the only crash log a
   mainline kernel produces.
4. Hands over to `/sbin/init` if another ramdisk provides one, or to `/bin/sh`
   when `rd.shell` is on the cmdline.
5. Otherwise stays alive as pid 1, because a kernel whose init exits panics with
   "Attempted to kill init".

`init --selftest` runs everything that does not need to be pid 1 (banner,
cmdline, pstore listing) and exits, which is how CI executes the same code on
the runner while the arm64 build is cross-compiled.

## Build

```bash
aarch64-linux-gnu-gcc -Os -static -Wall -Wextra -Werror -o init.aarch64 init.c
python3 scripts/mkinitramfs.py build --init init.aarch64 \
    --dir dev --dir proc --dir sys --dir sbin --dir tmp \
    --lz4 -o initramfs.cpio.lz4
python3 scripts/mkinitramfs.py verify --image initramfs.cpio.lz4 \
    --expect-init init.aarch64
```

`-static` matters: the ramdisk contains no libc, and CI fails the run if the
linked binary has a `PT_INTERP` segment. `--lz4` writes the same container the
device's stock ramdisk uses (`lz4 -l`, LZ4 legacy frame) and needs no config
change, because `CONFIG_RD_LZ4=y` is already asserted in the build.

## What is deliberately absent

No busybox, no shell, no Android `init`: those would make the ramdisk a
distribution rather than a bringup probe. When Android userspace needs to be
reached, the next step is a first-stage Android ramdisk, not more code here.
