# Patches

Board-specific deltas that cannot be expressed as a DTB (\`import/dts/\`) belong
here as \`git format-patch\` style files, applied in order by
\`scripts/prepare-tree.sh\` once the first one exists.

Expected first residents:

* panel driver for vayu's 1080x2400 DSI panel (only in the postmarketOS fork),
* touchscreen glue if the mainline driver needs the SKU's reset/irq ordering,
* any \`ath10k_snoc\` / WCN3990 firmware-path quirk.

Nothing is patched yet: P1 is "make the imported DTS compile on 6.18".
