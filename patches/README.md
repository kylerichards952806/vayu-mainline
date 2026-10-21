# Patches

`kernel/` is a vendored **shallow** tree (no `.git`), so fixes are applied to
the source in place and recorded as commits in *this* repo, not as a
`git format-patch` queue. Keep this directory for deltas that must stay
separable — things that are plausibly upstreamable and should be carried as
reviewable units rather than folded into the tree.

Expected first residents:

* panel driver for vayu's 1080x2400 DSI panel (only in the postmarketOS fork),
* touchscreen glue if the mainline driver needs the SKU's reset/irq ordering,
* any `ath10k_snoc` / WCN3990 firmware-path quirk.

Nothing is carried here yet: the only delta so far is the Bluetooth UART, which
lives directly in `kernel/arch/arm64/boot/dts/qcom/sm8150-xiaomi-vayu.dts` and is
documented in [../docs/PROVENANCE.md](../docs/PROVENANCE.md).
