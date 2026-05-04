#!/usr/bin/env python3
"""
bitmath — exploit-dev friendly bitwise calculator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
CLI layer. Parses arguments, reads stdin if needed, calls core.process(),
and prints the result. Contains zero business logic.

C-portability note: when a C port is written, this file becomes the only
thing that changes. core/engine.py translates 1-to-1 to C functions;
this file's argparse logic maps to a C getopt_long() block.
"""

import argparse
import os
import sys
from typing import Optional

# Always resolve the project root via __file__ so imports work regardless of
# the current working directory or how the script is invoked
# (./bitmath, python3 cli/bitmath.py, python3 -m cli.bitmath, etc.)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
 
from core.engine import (
    Base, GroupMode, Endian, FormatSpec, process
)


# ── argument parser ───────────────────────────────────────────────────────────

DESCRIPTION = "bitmath — exploit-dev friendly bitwise calculator"

EPILOG = """
LITERAL FORMATS
  0x1f        hex      (0x prefix)
  255         decimal  (plain integer)
  377o        octal    (trailing o)
  11111111b   binary   (trailing b)

AUTO-INFERENCE
  The output format mirrors the first literal in your expression:
    bitmath "0xc6 ^ 0x79"    →  0xbf   (hex in → hex out)
    bitmath "198 | 121"      →  255    (dec in → dec out)
    bitmath "1010b | 0101b"  →  1111   (bin in → bin out)
  Override with -x / -d / -o / -b.

EXAMPLES
  bitmath "0xc6 ^ 0x79"                    →  0xbf
  bitmath -a "0xdeadbeef"                  →  all representations
  bitmath -b -s "0xc6 ^ 0x79"              →  1011 1111
  bitmath -W 1 -s "0xdeadbeef"             →  de ad be ef
  bitmath -W 1 -s -e little "0xdeadbeef"   →  ef be ad de
  bitmath -E "0xdeadbeef"                  →  \\xde\\xad\\xbe\\xef
  bitmath --c-array "0xdeadbeef"           →  { 0xde, 0xad, 0xbe, 0xef }
  bitmath --ascii-decode "0x41414141"      →  AAAA
  bitmath --ascii-encode "AAAA"            →  0x41414141
  bitmath -t "0xff"                        →  -1     (signed 8-bit)
  bitmath -t -S 16 "0x8000"                →  -32768 (signed 16-bit)
  bitmath -t "-4 + -3"                     →  -7     (signed, width auto-inferred as 8)
  bitmath -v "0xc6 ^ 0x79"                 →  verbose parse info + 0xbf
  bitmath -S 32 "0xffffffff + 1"           →  0x0    (32-bit overflow)
  bitmath -x -u "0xdeadbeef"               →  0XDEADBEEF
  bitmath --width 64 "0xff"                →  0x00000000000000ff (via -W 1 -s)
  echo "0xc6 ^ 0x79" | bitmath             →  0xbf   (stdin)
"""

def build_parser() -> argparse.ArgumentParser:
    """Constructs and returns the argument parser."""
    p = argparse.ArgumentParser(
        prog="bitmath",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    # positional — optional so stdin works
    p.add_argument(
        "expression", nargs="?", default=None,
        metavar="EXPR",
        help="Bitwise/arithmetic expression (quote it). Reads stdin if omitted.",
    )

    out = p.add_argument_group("output format (overrides auto-inference)")
    out.add_argument("-x", dest="base", action="store_const", const="hex",
                     help="hex output (0xbf)")
    out.add_argument("-d", dest="base", action="store_const", const="dec",
                     help="decimal output (191)")
    out.add_argument("-o", dest="base", action="store_const", const="oct",
                     help="octal output (0o277)")
    out.add_argument("-b", dest="base", action="store_const", const="bin",
                     help="binary output, no leading zeros (10111111)")

    grp = p.add_argument_group("grouped hex view")
    grp.add_argument("-W", dest="byte_group", metavar="N", type=int, nargs="?",
                     const=2, default=None,
                     help="byte-grouped hex; N bytes per group (default 2)")
    grp.add_argument("-w", dest="nibble_group", metavar="N", type=int, nargs="?",
                     const=2, default=None,
                     help="nibble-grouped hex; N nibbles per group (default 2)")

    disp = p.add_argument_group("display options")
    disp.add_argument("-s", "--spaces", action="store_true",
                      help="add spaces between groups (works with -b, -W, -w)")
    disp.add_argument("-u", "--upper", action="store_true",
                      help="uppercase hex digits (DEADBEEF not deadbeef)")
    disp.add_argument("-P", "--no-prefix", dest="no_prefix", action="store_true",
                      help="omit 0x / 0b / 0o prefix from output")
    disp.add_argument("-e", "--endian", choices=["big", "little"], default="big",
                      metavar="ORDER",
                      help="byte order: big (default) or little")
    disp.add_argument("-S", "--size", "--width", dest="width", metavar="BITS",
                      type=int, default=None,
                      help="force display width: 8, 16, 32, 64 (also simulates overflow)")

    special = p.add_argument_group("special output modes")
    special.add_argument("-a", "--all", dest="show_all", action="store_true",
                         help="show hex, dec, oct, bin, bytes, ascii at once")
    special.add_argument("-E", "--escape", action="store_true",
                         help=r"C/Python \x escape sequence (\xde\xad\xbe\xef)")
    special.add_argument("--c-array", dest="c_array", action="store_true",
                         help="C byte-array literal ({ 0xde, 0xad, 0xbe, 0xef })")
    special.add_argument("--ascii-decode", dest="ascii_decode", action="store_true",
                         help="decode integer to ASCII string (0x41414141 -> AAAA)")
    special.add_argument("--ascii-encode", dest="ascii_encode", action="store_true",
                         help="encode ASCII string to hex integer ('AAAA' -> 0x41414141)")
    special.add_argument("-t", "--signed", action="store_true",
                         help="interpret result as signed two's complement (0xff -> -1)")
    special.add_argument("-v", "--verbose", action="store_true",
                         help="print parse/eval diagnostics to stderr before output")

    p.add_argument("-h", "--help", action="help",
                   help="show this help message and exit")

    return p


# ── flag validation / spec construction ──────────────────────────────────────

def build_spec(args: argparse.Namespace) -> FormatSpec:
    spec = FormatSpec()

    # base
    base_map = {"hex": Base.HEX, "dec": Base.DEC, "oct": Base.OCT, "bin": Base.BIN}
    spec.base = base_map.get(args.base)  # None → auto-infer

    # grouped mode (-W / -w are mutually exclusive)
    if args.byte_group is not None and args.nibble_group is not None:
        _die("-W and -w are mutually exclusive")
    if args.byte_group is not None:
        spec.group_mode = GroupMode.BYTE
        spec.group_n    = args.byte_group
    elif args.nibble_group is not None:
        spec.group_mode = GroupMode.NIBBLE
        spec.group_n    = args.nibble_group

    # warn: -x/-d/-o alongside -W/-w is silently ignored
    if spec.group_mode != GroupMode.NONE and args.base in ("hex", "dec", "oct"):
        _warn(f"-{args.base[0]} ignored when -W/-w is active (output is always hex)")

    # display
    spec.spaces       = args.spaces
    spec.upper        = args.upper
    spec.no_prefix    = args.no_prefix
    spec.endian       = Endian.LITTLE if args.endian == "little" else Endian.BIG
    spec.width        = args.width
    spec.show_all     = args.show_all
    spec.escape       = args.escape
    spec.c_array      = args.c_array
    spec.ascii_decode = args.ascii_decode
    spec.ascii_encode = args.ascii_encode
    spec.signed       = args.signed
    spec.verbose      = args.verbose
 
    # mutual exclusion check for output modes
    exclusive = [args.show_all, args.escape, args.c_array,
                 args.ascii_decode, args.ascii_encode]
    if sum(bool(x) for x in exclusive) > 1:
        _die("--all, --escape, --c-array, --ascii-decode, --ascii-encode are mutually exclusive")
 
    return spec


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _die(msg: str, code: int = 1) -> None:
    print(f"bitmath: error: {msg}", file=sys.stderr)
    sys.exit(code)

def _warn(msg: str) -> None:
    print(f"bitmath: note: {msg}", file=sys.stderr)

def _read_expr(args: argparse.Namespace) -> str:
    if args.expression:
        return args.expression.strip()
    if not sys.stdin.isatty():
        expr = sys.stdin.read().strip()
        if expr:
            return expr
    _die("no expression given; pass one as an argument or via stdin")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    expr   = _read_expr(args)
    spec   = build_spec(args)

    try:
        output, verbose = process(expr, spec)
    except ValueError as exc:
        _die(str(exc))

    if verbose:
        print(verbose, file=sys.stderr)

    print(output)


if __name__ == "__main__":
    main()
