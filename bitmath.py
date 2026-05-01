#!/usr/bin/env python3
import sys
import re
import argparse
from dataclasses import dataclass

# -------------------------------------------------------------------------
# C-Style Struct Equivalent
# -------------------------------------------------------------------------
@dataclass
class Config:
    mode_override: str = ""    # "x", "d", "o", "b"
    byte_mode: str = ""        # "W", "w"
    group_n: int = 2
    endian: str = "big"
    spaces: bool = False

    # Exploit-dev options
    bit_width: int = 0         # 0 means auto-infer. 8, 16, 32, 64 etc.
    ascii_decode: bool = False
    ascii_encode: bool = False
    verbose: bool = False
    signed: bool = False       # Two's complement interpretation

    raw_expr: str = ""

# -------------------------------------------------------------------------
# Argument Parsing (Translates to getopt_long in C)
# -------------------------------------------------------------------------
def parse_args() -> Config:
    """Parses command-line arguments and returns a Config object."""
    parser = argparse.ArgumentParser(
        description="bitmath - exploit-dev bitwise calculator",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  bitmath "0xc6 ^ 0x79"                        -> 0xbf
  bitmath "1100b ^ 1010b"                      -> 110
  bitmath -W 1 -s -e little "0xdeadbeef"       -> ef be ad de
  bitmath -S 32 "0xffffffff + 1"               -> 0x0  (simulates 32-bit overflow)
  bitmath -a "0x41414141"                      -> AAAA
  bitmath -t "-4 + -3"                         -> -7
"""
    )

    # Base output overrides
    group_out = parser.add_mutually_exclusive_group()
    group_out.add_argument("-x", action="store_const", dest="mode", const="x", help="force hex output")
    group_out.add_argument("-d", action="store_const", dest="mode", const="d", help="force decimal output")
    group_out.add_argument("-o", action="store_const", dest="mode", const="o", help="force octal output")
    group_out.add_argument("-b", action="store_const", dest="mode", const="b", help="force binary output")

    # Grouping
    parser.add_argument("-W", type=int, nargs="?", const=2, metavar="N", help="byte-grouped hex; N = bytes per group (default 2)")
    parser.add_argument("-w", type=int, nargs="?", const=2, metavar="N", help="nibble-grouped hex; N = nibbles per group (default 2)")

    # Formatting & Types
    parser.add_argument("-s", action="store_true", help="add spaces between groups")
    parser.add_argument("-e", choices=["big", "little"], default="big", help="endianness (default: big)")
    parser.add_argument("-S", "--size", type=int, default=0, help="force integer bit-width (8, 16, 32, 64) for overflow simulation")
    parser.add_argument("-a", "--ascii-decode", action="store_true", help="decode integer to ASCII string")
    parser.add_argument("-A", "--ascii-encode", action="store_true", help="encode ASCII string to hex integer")
    parser.add_argument("-t", "--signed", action="store_true", help="interpret decimal output as signed (Two's Complement)")
    parser.add_argument("-v", "--verbose", action="store_true", help="show intermediate parsing steps")

    # Positional expression
    parser.add_argument("expr", nargs=argparse.REMAINDER, help="math expression")

    args = parser.parse_args()

    cfg = Config()
    if args.mode: cfg.mode_override = args.mode

    if args.W is not None:
        cfg.byte_mode = "W"
        cfg.group_n = args.W
    elif args.w is not None:
        cfg.byte_mode = "w"
        cfg.group_n = args.w

    cfg.spaces = args.s
    cfg.endian = args.e
    cfg.bit_width = args.size
    cfg.ascii_decode = args.ascii_decode
    cfg.ascii_encode = args.ascii_encode
    cfg.verbose = args.verbose
    cfg.signed = args.signed

    cfg.raw_expr = " ".join(args.expr).strip()

    if not cfg.raw_expr:
        parser.print_help()
        sys.exit(1)

    # -e little with no explicit group mode implies -W
    if cfg.endian == "little" and not cfg.byte_mode:
        cfg.byte_mode = "W"

    return cfg

# -------------------------------------------------------------------------
# Parsing & Lexing
# -------------------------------------------------------------------------
def detect_inferred_mode(expr: str) -> str:
    """Infers default output type from input literals."""
    tokens = expr.split()
    for tok in tokens:
        if re.match(r"^-?0[xX][0-9a-fA-F]+$", tok): return "x"
        if re.match(r"^-?[0-9]+[oO]$", tok): return "o"
        if re.match(r"^-?[01]+[bB]$", tok): return "b"
        if re.match(r"^-?[0-9]+$", tok): return "d"
    return "d"

def preprocess_expression(expr: str) -> str:
    """Converts custom suffixes into Python-eval friendly prefixes."""
    # NNNo -> 0oNNN
    expr = re.sub(r"(^|[^0-9a-fA-F_])([0-9]+)[oO]\b", r"\g<1>0o\g<2>", expr)
    # NNNb -> 0bNNN
    expr = re.sub(r"(^|[^0-9a-fA-F_])([01]+)[bB]\b", r"\g<1>0b\g<2>", expr)
    return expr

def infer_width(raw_expr: str, result: int) -> int:
    """Find the widest literal in the expression to determine byte-bounds."""
    max_bits = 1

    # Extract all hex, bin, oct, and dec literals
    literals = re.finditer(r"-?0[xX][0-9a-fA-F]+|-?0[bB][01]+|-?0[oO][0-7]+|-?\b\d+\b", raw_expr)
    for match in literals:
        val = int(match.group(0), 0)
        # If negative, we need to consider the bit length of its absolute + 1 for the sign bit
        bits_needed = val.bit_length() + (1 if val < 0 else 0)
        max_bits = max(max_bits, bits_needed)

    res_bits = result.bit_length() + (1 if result < 0 else 0)
    needed = max(max_bits, res_bits)

    width = 8
    while width < needed:
        width *= 2

    return width

# -------------------------------------------------------------------------
# Evaluation (Future C Port: Replace with Shunting-yard AST Parser)
# -------------------------------------------------------------------------
def evaluate_expression(py_expr: str) -> int:
    """Evaluates the expression in a safe context."""
    try:
        # C-PORT NOTE: This is where a C rewrite requires a custom parser.
        return eval(py_expr, {"__builtins__": {}})
    except Exception as error:
        print(f"error evaluating expression: {error}", file=sys.stderr)
        sys.exit(1)

# -------------------------------------------------------------------------
# Formatting & Output
# -------------------------------------------------------------------------
def format_ascii(val: int, width_bits: int) -> str:
    """Convert integer to an ASCII string representation."""
    byte_len = max(1, width_bits // 8)
    hex_str = format(val, f"0{byte_len * 2}x")

    ascii_out = ""
    for i in range(0, len(hex_str), 2):
        byte_val = int(hex_str[i:i+2], 16)
        if 32 <= byte_val <= 126:
            ascii_out += chr(byte_val)
        else:
            ascii_out += "."
    return ascii_out

def format_standard(val: int, mode: str, width_bits: int, cfg: Config) -> str:
    """Formats the integer according to the specified mode."""
    if mode == "d":
        if cfg.signed:
            msb_mask = 1 << (width_bits - 1)
            # If the MSB is 1, the number is negative
            if val & msb_mask:
                val = val - (1 << width_bits)
        return str(val)

    elif mode == "x":
        return f"0x{val:x}"
    elif mode == "o":
        return f"0o{val:o}"
    elif mode == "b":
        raw = format(val, "b") if val > 0 else "0"
        if cfg.spaces:
            # Pad to nearest nibble boundary
            pad = (4 - len(raw) % 4) % 4
            raw = raw.zfill(len(raw) + pad)
            groups = [raw[i:i+4] for i in range(0, len(raw), 4)]
            while len(groups) > 1 and groups[0] == "0000":
                groups.pop(0)
            return " ".join(groups)
        return raw
    return ""

def format_grouped(val: int, width_bits: int, cfg: Config) -> str:
    """Formats the integer into byte/nibble groups with endianness."""
    total_bytes = width_bits // 8
    hex_str = format(val, f"0{total_bytes * 2}x")
    nibbles = list(hex_str)

    if cfg.endian == "little":
        # C-PORT NOTE: Standard byte-swap algorithm
        byte_list = [nibbles[i*2:(i+1)*2] for i in range(total_bytes)]
        byte_list.reverse()
        nibbles = [c for pair in byte_list for c in pair]

    chunk = cfg.group_n * 2 if cfg.byte_mode == "W" else cfg.group_n
    groups = ["".join(nibbles[i:i+chunk]) for i in range(0, len(nibbles), chunk)]

    sep = " " if cfg.spaces else ""
    return sep.join(groups)

# -------------------------------------------------------------------------
# Main Execution
# -------------------------------------------------------------------------
def main():
    """Main function to orchestrate parsing, evaluation, and output."""
    cfg = parse_args()

    if cfg.ascii_encode:
        raw_result = int.from_bytes(cfg.raw_expr.encode("utf-8"), byteorder="big")
        output_mode = cfg.mode_override or "x"
        width = cfg.bit_width if cfg.bit_width > 0 else max(8, len(cfg.raw_expr) * 8)

        if cfg.verbose:
            print(f"[+] String Encoding Mode: '{cfg.raw_expr}'")

    else:
        output_mode = cfg.mode_override or detect_inferred_mode(cfg.raw_expr)
        py_expr = preprocess_expression(cfg.raw_expr)
        raw_result = evaluate_expression(py_expr)

        if cfg.ascii_decode and cfg.bit_width == 0:
            # Get exact bit length, round up to nearest multiple of 8 (nearest byte)
            width = max(8, (raw_result.bit_length() + 7) // 8 * 8)
        else:
            width = cfg.bit_width if cfg.bit_width > 0 else infer_width(cfg.raw_expr, raw_result)

        if cfg.verbose:
            print(f"[+] Parsed Python Expr: {py_expr}")

    # Mask to width (Simulates integer overflow naturally)
    unsigned_result = raw_result & ((1 << width) - 1)

    if cfg.verbose:
        print(f"[+] Calculated Width   : {width} bits")
        print(f"[+] Output Mode        : {output_mode}")
        print(f"[+] Unsigned Int Val   : {unsigned_result}")
        print("-" * 40)

    # Output selection
    if cfg.ascii_decode:
        print(format_ascii(unsigned_result, width))
    elif cfg.byte_mode:
        print(format_grouped(unsigned_result, width, cfg))
    else:
        print(format_standard(unsigned_result, output_mode, width, cfg))

if __name__ == "__main__":
    main()
