# Config references

The **build** config is plain `make defconfig` (see the CI workflow): a neutral
arm64 base. The Android 17 config for vayu is P2 work and does not exist yet.

What is here now is reference material, not a config that is merged:

- `reference-postmarketos-sm8150.aarch64` — the 7,968-line postmarketOS SM8150
  config. Useful only as a cross-check for *which drivers* a working mainline
  SM8150 uses (`ATH10K_SNOC`, `QCOM_IPA`, `QCOM_FASTRPC`, …). It targets a
  non-Android userspace and must not be treated as the target config.

The config chain that matters for this device is the LineageOS 24.0 5.4 one:

```
vendor/sm8150-qgki_defconfig
vendor/xiaomi/sm8150-common.config
vendor/xiaomi/vayu.config
```

It lives in the 5.4 tree (`mirrors/android_kernel_xiaomi_sm8150.git`, branch
`MI_SM8150_5.4`). Its options cannot be replayed one-for-one on 6.18 — most of
the Qualcomm techpack symbols have no counterpart — so the portable subset has
to be re-derived per subsystem. See [../../docs/REFERENCE.md](../../docs/REFERENCE.md).
