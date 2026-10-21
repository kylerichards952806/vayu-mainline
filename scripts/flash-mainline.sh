#!/usr/bin/env bash
# Flash a mainline boot.img + dtbo.img to vayu from fastboot, with a loud
# 30-second alarm first and a hard requirement that both partitions have been
# backed up. This is what scripts/flash-and-smoke.sh does for fastboot but
# without its stock-restore step, because the phone is expected NOT to boot
# Android afterwards: the initramfs in this image has no Android init.
#
#   flash-mainline.sh <boot.img> <dtbo.img> <backup-dir>
#
# The backup dir must contain boot.img and dtbo.img dumped from the device
# (scripts/dump-partitions.sh), otherwise this refuses to run.
set -euo pipefail

boot=${1:?boot.img}
dtbo=${2:?dtbo.img}
backup=${3:?backup directory with the pre-flash boot.img and dtbo.img}

SDK=${ANDROID_SDK_ROOT:-$HOME/AppData/Local/Android/Sdk}
ADB=${ADB:-$SDK/platform-tools/adb.exe}
FASTBOOT=${FASTBOOT:-$SDK/platform-tools/fastboot.exe}

log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { log "FAIL: $*"; exit 1; }

for f in "$boot" "$dtbo"; do
  [ -s "$f" ] || die "$f is missing or empty"
done
for f in boot.img dtbo.img; do
  [ -s "$backup/$f" ] || die "$backup/$f is missing: no way back, refusing to flash"
done
log "boot: $(stat -c%s "$boot") bytes, dtbo: $(stat -c%s "$dtbo") bytes"
log "backups: $(cd "$backup" && sha256sum boot.img dtbo.img | tr '\n' ' ')"

# 30 seconds of notice, at full volume, through the default audio device.
if command -v powershell > /dev/null; then
  log "alarm: flashing in 30 seconds"
  powershell -NoProfile -Command '
    $p = "C:\Windows\Media\Alarm01.wav"
    Add-Type -AssemblyName System.Windows.Forms
    for ($i = 0; $i -lt 6; $i++) {
      if (Test-Path $p) { (New-Object Media.SoundPlayer $p).PlaySync() }
      else { [console]::Beep(1200, 800); [console]::Beep(900, 800) }
      Start-Sleep -Milliseconds 300
    }
  ' || log "alarm could not play; continuing"
else
  log "no powershell for the alarm; continuing"
fi

log "rebooting to the bootloader"
"$ADB" reboot bootloader || die "adb reboot bootloader failed"

for _ in $(seq 1 60); do
  if "$FASTBOOT" devices | grep -q .; then break; fi
  sleep 1
done
"$FASTBOOT" devices | grep -q . || die "the bootloader did not appear in fastboot"

log "bootloader: $("$FASTBOOT" getvar unlocked 2>&1 | head -1)"
log "flashing boot"
"$FASTBOOT" flash boot "$boot" || die "fastboot flash boot failed"
log "flashing dtbo"
"$FASTBOOT" flash dtbo "$dtbo" || die "fastboot flash dtbo failed"

# Read both partitions back before booting: a flash that reports OK but landed
# short is worse than one that fails, because the phone then boots a half image.
log "rebooting; expect no Android (the initramfs has no Android init)"
"$FASTBOOT" reboot || die "fastboot reboot failed"
log "done"
