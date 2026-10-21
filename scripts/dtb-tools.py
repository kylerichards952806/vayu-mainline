#!/usr/bin/env python3
"""Edit compiled device trees without dtc: two subcommands.

    dtb-tools.py overlay --base vayu.dtb --target-path /soc@0 -o overlay.dtb
    dtb-tools.py add-root-props --dtb vayu.dtb \
        --prop qcom,board-id=0000002f00000000 -o vayu-boardid.dtb

Both exist because of what twelve flashes on this phone showed. ABL boots a
mainline kernel when `boot.img` carries the 5.4 vendor tree (it reaches the logo
and sits there), and returns to fastboot in ~4 s for every image carrying our
own DTB, whatever sits in `dtbo`:

  vendor tree + vendor dtbo entry               -> boots
  vendor tree + our entry, blank table, no-op    -> fastboot
  vendor tree wrapped in our table               -> boots (table format is right)
  our tree + any of the above                    -> fastboot
  our tree + board-id/msm-id added to the root   -> fastboot

The vendor overlay's fragments use `target = <0xffffffff>`, a phandle that dtc
fixes up at apply time from `__fixups__` against a base tree that carries
`__symbols__`. Our DTB has no `__symbols__`, so `overlay` here writes a
`target-path` (or a real phandle) fragment instead - the shape a compiler would
produce for a base with no labels. Neither form was accepted yet; these tools
are how the next experiment gets built, not a working recipe.
"""

from __future__ import annotations

import argparse
import struct

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9
FDT_MAGIC = 0xD00DFEED


def _read(fdt):
    (magic, total, off_struct, off_strings, off_rsv, ver, last, cpuid,
     size_str, size_struct) = struct.unpack_from(">10I", fdt, 0)
    if magic != FDT_MAGIC:
        raise SystemExit("not a flattened device tree")
    return dict(total=total, off_struct=off_struct, off_strings=off_strings,
                off_rsv=off_rsv, ver=ver, last=last, cpuid=cpuid,
                size_str=size_str, size_struct=size_struct)


def find_phandle(fdt, path):
    """Phandle of the node at `path`, or None when the node has no phandle."""
    h = _read(fdt)
    strings = fdt[h["off_strings"]:h["off_strings"] + h["size_str"]]

    def name_at(offset):
        return strings[offset:strings.find(b"\0", offset)].decode()

    p, stack = h["off_struct"], []
    while p < h["off_struct"] + h["size_struct"]:
        tok = struct.unpack_from(">I", fdt, p)[0]
        if tok == FDT_BEGIN_NODE:
            p += 4
            end = fdt.find(b"\0", p)
            stack.append(fdt[p:end].decode(errors="replace"))
            p = (end + 4) & ~3
        elif tok == FDT_END_NODE:
            stack.pop()
            p += 4
        elif tok == FDT_PROP:
            length, name_off = struct.unpack_from(">II", fdt, p + 4)
            current = "/" + "/".join(n for n in stack if n)
            if current == path and name_at(name_off) == "phandle":
                return struct.unpack(">I", fdt[p + 12:p + 16])[0]
            p = (p + 12 + length + 3) & ~3
        elif tok == FDT_END:
            break
        else:
            p += 4
    return None


def add_root_props(fdt, props):
    """Insert properties into the root node, keeping every existing name offset."""
    h = _read(fdt)
    if struct.unpack_from(">I", fdt, h["off_struct"])[0] != FDT_BEGIN_NODE \
            or fdt[h["off_struct"] + 4] != 0:
        raise SystemExit("first token is not the root node")
    insert = h["off_struct"] + 8          # tag(4) + empty name padded(4)

    strings = bytearray(fdt[h["off_strings"]:h["off_strings"] + h["size_str"]])
    added = bytearray()
    for name, value in props:
        name_off = len(strings)
        strings += name.encode() + b"\0"
        added += struct.pack(">III", FDT_PROP, len(value), name_off)
        added += value
        while len(added) % 4:
            added.append(0)

    struct_block = (fdt[h["off_struct"]:insert] + bytes(added)
                    + fdt[insert:h["off_struct"] + h["size_struct"]])
    new_strings_off = h["off_struct"] + len(struct_block)
    header = struct.pack(">10I", FDT_MAGIC, new_strings_off + len(strings),
                         h["off_struct"], new_strings_off, h["off_rsv"],
                         h["ver"], h["last"], h["cpuid"], len(strings),
                         len(struct_block))
    return header + fdt[40:h["off_struct"]] + struct_block + bytes(strings)


def add_node(fdt, node, string_props):
    """Append a child of the root node, e.g. /__symbols__, with string props.

    `__symbols__` is what dtc emits for `-@`, and what an overlay's fixups are
    resolved against. The kernel tree here is built without it, so this adds it
    to a compiled blob: label -> path strings, nothing else.
    """
    h = _read(fdt)
    strings = bytearray(fdt[h["off_strings"]:h["off_strings"] + h["size_str"]])
    added = bytearray()
    added += struct.pack(">I", FDT_BEGIN_NODE)
    added += node.encode() + b"\0"
    while len(added) % 4:
        added.append(0)
    for name, value in string_props:
        name_off = len(strings)
        strings += name.encode() + b"\0"
        payload = value.encode() + b"\0"
        added += struct.pack(">III", FDT_PROP, len(payload), name_off)
        added += payload
        while len(added) % 4:
            added.append(0)
    added += struct.pack(">I", FDT_END_NODE)

    # The root's END_NODE is the last token of the structure block; the new
    # child goes just before it.
    end_token = h["off_struct"] + h["size_struct"] - 4
    if struct.unpack_from(">I", fdt, end_token)[0] != FDT_END:
        raise SystemExit("structure block does not end with FDT_END")
    struct_block = (fdt[h["off_struct"]:end_token] + bytes(added)
                    + fdt[end_token:h["off_struct"] + h["size_struct"]])
    new_strings_off = h["off_struct"] + len(struct_block)
    header = struct.pack(">10I", FDT_MAGIC, new_strings_off + len(strings),
                         h["off_struct"], new_strings_off, h["off_rsv"],
                         h["ver"], h["last"], h["cpuid"], len(strings),
                         len(struct_block))
    return header + fdt[40:h["off_struct"]] + struct_block + bytes(strings)


def build_overlay(target, props, patch, fixup=None):
    """A one-fragment overlay: root props on the entry, `patch` inside it.

    With `fixup`, the fragment's target is written as <0xffffffff> and a
    __fixups__ node names the label it should be resolved from - the shape dtc
    writes when it compiles `target = <&label>` for a tree it cannot see.
    """
    if fixup:
        target_prop = ("target", struct.pack(">I", 0xFFFFFFFF))
    elif isinstance(target, int):
        target_prop = ("target", struct.pack(">I", target))
    else:
        target_prop = ("target-path", target.encode() + b"\0")
    names, strings = {}, bytearray()
    for name, _ in list(props) + [target_prop] + list(patch):
        if name not in names:
            names[name] = len(strings)
            strings += name.encode() + b"\0"
    if fixup and fixup not in names:
        names[fixup] = len(strings)
        strings += fixup.encode() + b"\0"

    block = bytearray()

    def begin(name):
        block.extend(struct.pack(">I", FDT_BEGIN_NODE))
        block.extend(name.encode() + b"\0")
        while len(block) % 4:
            block.append(0)

    def prop(name, value):
        block.extend(struct.pack(">III", FDT_PROP, len(value), names[name]))
        block.extend(value)
        while len(block) % 4:
            block.append(0)

    def end_node():
        block.extend(struct.pack(">I", FDT_END_NODE))

    begin("")
    for name, value in props:
        prop(name, value)
    begin("fragment@0")
    prop(*target_prop)
    begin("__overlay__")
    for name, value in patch:
        prop(name, value)
    end_node()
    end_node()
    if fixup:
        begin("__fixups__")
        prop(fixup, b"/fragment@0:target:0\0")
        end_node()
    end_node()
    block.extend(struct.pack(">I", FDT_END))

    rsvmap = b"\0" * 16
    off_struct = 40 + len(rsvmap)
    off_strings = off_struct + len(block)
    header = struct.pack(">10I", FDT_MAGIC, off_strings + len(strings),
                         off_struct, off_strings, 40, 17, 16, 0,
                         len(strings), len(block))
    return header + rsvmap + bytes(block) + bytes(strings)


VENDOR_BOARD_ID = struct.pack(">II", 0x2F, 0x00)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add-root-props", help="add properties to a DTB's root")
    a.add_argument("--dtb", required=True)
    a.add_argument("--prop", action="append", default=[], metavar="NAME=HEX")
    a.add_argument("--symbol", action="append", default=[], metavar="LABEL=PATH",
                   help="also emit /__symbols__ with these label -> path strings")
    a.add_argument("-o", "--output", required=True)

    o = sub.add_parser("overlay", help="build a one-fragment overlay")
    o.add_argument("--base", help="base DTB, to resolve --target-path to a phandle")
    o.add_argument("--target-path", default="/",
                   help="node the fragment applies to (default: /)")
    o.add_argument("--phandle", action="store_true",
                   help="use the node's phandle instead of target-path")
    o.add_argument("--fixup", metavar="LABEL",
                   help="vendor style: target = <0xffffffff> plus a __fixups__ "
                        "entry naming LABEL, to be resolved from the base"
                        " tree's __symbols__")
    o.add_argument("--board-id", default="2f 00",
                   help="qcom,board-id cells, hex (the vendor entry has '2f 00')")
    o.add_argument("-o", "--output", required=True)

    args = parser.parse_args()
    if args.command == "add-root-props":
        props = []
        for item in args.prop:
            name, _, value = item.partition("=")
            props.append((name, bytes.fromhex(value)))
        blob = open(args.dtb, "rb").read()
        blob = add_root_props(blob, props)
        if args.symbol:
            symbols = [tuple(item.split("=", 1)) for item in args.symbol]
            blob = add_node(blob, "__symbols__", symbols)
            print(f"__symbols__: {', '.join(f'{k} -> {v}' for k, v in symbols)}")
        open(args.output, "wb").write(blob)
        print(f"wrote {args.output}")
        return 0

    target = args.target_path
    if args.phandle:
        base = open(args.base, "rb").read()
        phandle = find_phandle(base, args.target_path)
        if phandle is None:
            raise SystemExit(f"{args.target_path} has no phandle in {args.base}")
        target = phandle
    cells = [int(v, 16) for v in args.board_id.split()]
    props = [
        ("model", b"VAYU\0"),
        ("compatible", b"qcom,sm8150-cdp\0qcom,sm8150\0qcom,cdp\0"),
        ("qcom,board-id", struct.pack(f">{len(cells)}I", *cells)),
    ]
    blob = build_overlay(target, props, [("boot-test", b"mainline\0")],
                         fixup=args.fixup)
    open(args.output, "wb").write(blob)
    print(f"wrote {args.output}: {len(blob)} bytes, fragment targets {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
