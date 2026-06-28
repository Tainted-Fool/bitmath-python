"""
bitmath.core.engine
~~~~~~~~~~~~~~~~~~~
Pure business logic: expression evaluation, width inference, and all
formatting.  No argparse, no sys.argv, no I/O — only functions that
take plain Python values and return plain Python values.

C-portability contract
~~~~~~~~~~~~~~~~~~~~~~
Every function in this module has a direct C equivalent. The mapping is:
  Python function          C function (future)
  translate_expr()         core_translate_expr()
  evaluate()               core_evaluate()        (wraps mpz or __int128)
  infer_width()            core_infer_width()
  mask_unsigned()          core_mask_unsigned()
  detect_infix_base()      core_detect_infix_base()
  fmt_*()                  core_fmt_*()

Keep this file free of:
  - argparse / sys / os / subprocess
  - print() calls
  - Any I/O whatsoever

The only acceptable imports are: re, math, and the standard library types.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from enum import Enum, auto


# ── enums ─────────────────────────────────────────────────────────────────────

class Base(Enum):
    HEX = auto()
    DEC = auto()
    OCT = auto()
    BIN = auto()
    ASC = auto()   # NEW: -a flag → ascii output format


class GroupMode(Enum):
    NONE   = auto()
    BYTE   = auto()
    NIBBLE = auto()


class Endian(Enum):
    BIG    = auto()
    LITTLE = auto()


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class FormatSpec:
    """All display options in one place. Mirrors what the CLI parses."""
    base:         Base | None    = None        # None → auto-infer
    group_mode:   GroupMode      = GroupMode.NONE
    group_n:      int            = 2
    endian:       Endian         = Endian.BIG
    spaces:       bool           = False
    upper:        bool           = False
    no_prefix:    bool           = False
    escape:       bool           = False
    c_array:      bool           = False
    show_all:     bool           = False       # -A flag
    ascii_out:    bool           = False       # NEW: -a flag (ascii output format)
    width:        int | None     = None
    signed:       bool           = False
    ascii_decode: bool           = False
    ascii_encode: bool           = False
    verbose:      bool           = False


@dataclass
class EvalResult:
    """Everything produced by a single expression evaluation."""
    unsigned:       int
    width:          int
    inferred_base:  Base


@dataclass
class VerboseInfo:
    """
    Intermediate parsing/eval steps surfaced by --verbose.
    C equivalent: core_verbose_info struct printed to stderr by core_process().
    """
    py_expr:    str
    raw_int:    int
    unsigned:   int
    width:      int
    inferred_base: Base


# ── literal translation ───────────────────────────────────────────────────────

_RE_OCT_SUFFIX = re.compile(r"(?<![0-9a-fA-F_])([0-9]+)[oO](?![0-9a-fA-F_])")
_RE_BIN_SUFFIX = re.compile(r"(?<![0-9a-fA-F_])([01]+)[bB](?![0-9a-fA-F_])")


def translate_expr(expr: str) -> str:
    """
    Rewrite custom literal suffixes to Python-native form.
      377o  → 0o377
      1101b → 0b1101
    Hex and decimal pass through unchanged.
    C equivalent: core_translate_expr()
    """
    result = expr
    result = _RE_OCT_SUFFIX.sub(r"0o\1", result)
    result = _RE_BIN_SUFFIX.sub(r"0b\1", result)
    return result


# ── safe evaluator ────────────────────────────────────────────────────────────

_SAFE_GLOBALS: dict = {"__builtins__": {}}


def evaluate(expr: str) -> int:
    """
    Evaluate a bitwise/arithmetic expression string.
    Returns a raw Python int (may be negative, e.g. from ~).
    Raises ValueError on invalid input.
    C equivalent: core_evaluate() (wraps mpz or __int128)
    """
    py = translate_expr(expr)
    try:
        result = eval(py, _SAFE_GLOBALS)  # noqa: S307
    except Exception as exc:
        raise ValueError(f"invalid expression: {exc}") from exc
    if not isinstance(result, int):
        raise ValueError(f"expression must evaluate to an integer, got {type(result).__name__}")
    return result


# ── width inference ───────────────────────────────────────────────────────────

_RE_LITERALS = re.compile(r"0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\b\d+\b")


def _next_pow2_bytes(bits: int) -> int:
    """Round `bits` up to the next power-of-2 bit count (min 8)."""
    minimum = 8
    n = max(minimum, bits)
    # round up to next power-of-2
    p = 1
    while p < n:
        p <<= 1
    return p


def infer_width(py_expr: str, result: int, override: int | None = None) -> int:
    """
    Return the display bit-width for `result` given the expression's literals.
    `py_expr` must already be translated (0o / 0b prefixes, not o/b suffixes).
    C equivalent: core_infer_width()
    """
    if override is not None:
        valid = {8, 16, 32, 64, 128, 256}
        if override not in valid:
            raise ValueError(f"--width must be 8, 16, 32, 64, 128, or 256; got {override}")
        return override

    # find widest literal
    max_literal_bits = 0
    for m in _RE_LITERALS.finditer(py_expr):
        tok = m.group()
        val = int(tok, 0)
        max_literal_bits = max(max_literal_bits, val.bit_length())

    # also consider the result itself
    res_bits = result.bit_length() if result >= 0 else (~result).bit_length() + 1
    needed = max(max_literal_bits, res_bits, 1)
    return _next_pow2_bytes(needed)


# ── masking ───────────────────────────────────────────────────────────────────

def mask_unsigned(value: int, width: int) -> int:
    """
    Mask `value` to `width` bits, producing an unsigned integer.
    C equivalent: core_mask_unsigned()
    """
    return value & ((1 << width) - 1)


# ── base detection ────────────────────────────────────────────────────────────

_RE_FIRST_LITERAL = re.compile(
    r"0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|[01]+[bB]|[0-9]+[oO]|\b[0-9]+\b"
)


def detect_infix_base(expr: str) -> Base:
    """
    Return the Base implied by the first literal token in `expr`.
    Falls back to DEC if nothing is recognised.
    C equivalent: core_detect_infix_base()
    """
    m = _RE_FIRST_LITERAL.search(expr)
    if not m:
        return Base.DEC
    tok = m.group()
    if tok.startswith(("0x", "0X")):
        return Base.HEX
    if tok.startswith(("0b", "0B")) or tok.endswith(("b", "B")):
        return Base.BIN
    if tok.startswith(("0o", "0O")) or tok.endswith(("o", "O")):
        return Base.OCT
    return Base.DEC


# ── scalar formatters ─────────────────────────────────────────────────────────

def fmt_hex(n: int, upper: bool = False, prefix: bool = True) -> str:
    """Format as hex. `prefix` controls the 0x leader."""
    h = format(n, "X" if upper else "x")
    if prefix:
        return ("0X" if upper else "0x") + h
    return h


def fmt_dec(n: int) -> str:
    """ Format as decimal. Always returns a plain string (no prefix)."""
    return str(n)


def fmt_oct(n: int, prefix: bool = True) -> str:
    """Format as octal. `prefix` controls the 0o leader."""
    return ("0o" if prefix else "") + format(n, "o")


def fmt_bin(n: int, spaces: bool = False, prefix: bool = False) -> str:
    """
    Binary without leading zeros. With `spaces`, nibble-groups are
    space-separated; a leading all-zero nibble is stripped.
    """
    raw = format(n, "b") if n > 0 else "0"
    if not spaces:
        return ("0b" if prefix else "") + raw
    # pad to multiple of 4
    pad = (-len(raw)) % 4
    padded = "0" * pad + raw
    groups = [padded[i:i+4] for i in range(0, len(padded), 4)]
    # strip leading all-zero group
    if groups and groups[0] == "0000":
        groups = groups[1:]
    result = " ".join(groups) if groups else "0"
    return ("0b " if prefix else "") + result


def fmt_signed(n: int, width: int) -> str:
    """
    Interpret `n` as a two's-complement signed integer of `width` bits.
    C equivalent: core_fmt_signed() using (int64_t) cast or equivalent.
      0xff (8-bit) → -1
      0x80 (8-bit) → -128
      0x7f (8-bit) → 127
    """
    msb_mask = 1 << (width - 1)
    if n & msb_mask:
        return str(n - (1 << width))
    return str(n)


def fmt_ascii_decode(n: int, width: int, endian: Endian = Endian.BIG) -> str:
    """
    Decode an integer to its ASCII string representation, using all `width` bits.
    Non-printable bytes are rendered as dots (like xxd / strings behaviour).
    C equivalent: core_fmt_ascii_decode() iterating bytes MSB-first (or LSB-first
    for little -endian).
      0x414243   → .ABC  (32-bit padded)
      0x414243   → CBA. (bytes reversed)
      0x41414141 → AAAA
    """
    byte_len  = (width + 7) // 8
    hex_str   = format(n, f"0{byte_len * 2}x")
    byte_vals = [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]
    if endian == Endian.LITTLE:
        byte_vals = list(reversed(byte_vals))
    return "".join(chr(b) if 0x20 <= b <= 0x7e else "." for b in byte_vals)


def fmt_ascii(n: int, width: int, endian: Endian = Endian.BIG) -> str:
    """
    Format integer as ASCII for the -a output flag.
    Strips leading zero-padding bytes so values like 0x68656c6c6f show as "hello".
    Non-printable bytes render as dots.
    Respects endianness: little-endian reverses the byte order before rendering.
    Used by -a (ascii output flag).
    """
    if n == 0:
        return "."
    val_bytes = (n.bit_length() + 7) // 8
    hex_str   = format(n, f"0{val_bytes * 2}x")
    byte_vals = [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]
    if endian == Endian.LITTLE:
        byte_vals = list(reversed(byte_vals))
    return "".join(chr(b) if 0x20 <= b <= 0x7e else "." for b in byte_vals)


def ascii_encode(s: str, endian: Endian = Endian.BIG) -> int:
    """
    Encode an ASCII string to its integer representation.
    Big-endian: first char in most-significant byte.
    Little-endian: first char in least-significant byte (reversed).
    C equivalent: core_ascii_encode()
      "ABC" big    → 0x414243
      "ABC" little → 0x434241
    """
    b = s.encode("latin-1")
    if endian == Endian.LITTLE:
        b = bytes(reversed(b))
    return int.from_bytes(b, byteorder="big")


# ── grouped hex helpers ───────────────────────────────────────────────────────

def _nibble_list(n: int, width: int) -> list[str]:
    """Return a flat list of `width//4` hex nibble chars, MSB-first."""
    return list(format(n, f"0{width // 4}x"))


def _apply_endian(nibbles: list[str], endian: Endian) -> list[str]:
    """Reverse at byte granularity for little-endian."""
    if endian == Endian.BIG:
        return nibbles
    # swap pairs of nibbles (= bytes)
    byte_count = len(nibbles) // 2
    pairs = [nibbles[i*2:i*2+2] for i in range(byte_count)]
    pairs.reverse()
    return [n for p in pairs for n in p]


def fmt_grouped(n: int, width: int, mode: GroupMode, group_n: int, endian: Endian = Endian.BIG, spaces: bool = False, upper: bool = False) -> str:
    """
    Byte-grouped (-W) or nibble-grouped (-w) hex output.
    mode=BYTE:   group_n is in bytes   → chunk = group_n * 2 nibbles
    mode=NIBBLE: group_n is in nibbles → chunk = group_n nibbles
    """
    nibs = _nibble_list(n, width)
    nibs = _apply_endian(nibs, endian)
    if upper:
        nibs = [c.upper() for c in nibs]

    chunk = group_n * 2 if mode == GroupMode.BYTE else group_n
    groups = ["".join(nibs[i:i+chunk]) for i in range(0, len(nibs), chunk)]
    sep = " " if spaces else ""
    return sep.join(groups)


# ── special formatters ────────────────────────────────────────────────────────

def fmt_escape(n: int, width: int, endian: Endian, upper: bool = False) -> str:
    r"""Format as \xNN\xNN... escape sequence."""
    nibs = _nibble_list(n, width)
    nibs = _apply_endian(nibs, endian)
    if upper:
        nibs = [c.upper() for c in nibs]
    pairs = ["".join(nibs[i:i+2]) for i in range(0, len(nibs), 2)]
    return "".join(f"\\x{p}" for p in pairs)


def fmt_c_array(n: int, width: int, endian: Endian, upper: bool = False) -> str:
    """Format as a C byte-array literal: { 0xde, 0xad, 0xbe, 0xef }"""
    nibs = _nibble_list(n, width)
    nibs = _apply_endian(nibs, endian)
    if upper:
        nibs = [c.upper() for c in nibs]
    pairs = ["".join(nibs[i:i+2]) for i in range(0, len(nibs), 2)]
    prefix = "0X" if upper else "0x"
    elems = ", ".join(f"{prefix}{p}" for p in pairs)
    return "{ " + elems + " }"


def fmt_all(n: int, width: int, signed: bool = False, upper: bool = False, endian: Endian = Endian.BIG) -> dict[str, str]:
    """
    Return an ordered dict of all representations.
    Used by --all / -A mode.
    """
    h = format(n, "X" if upper else "x")
    pref = "0X" if upper else "0x"
    rows: dict[str, str] = {
        "hex":   pref + h,
        "dec":   str(n),
        "oct":   "0o" + format(n, "o"),
        "bin":   fmt_bin(n, spaces=True),
        "bytes": fmt_grouped(n, width, GroupMode.BYTE, 1, endian=endian, spaces=True, upper=upper),
        "ascii": fmt_ascii_decode(n, width, endian=endian),
    }
    if signed:
        rows["signed"] = fmt_signed(n, width)
    rows["width"] = f"{width}-bit"
    return rows


def fmt_verbose(info: VerboseInfo) -> str:
    """
    Format VerboseInfo as a multi-line diagnostic block.
    Returned as a string — the CLI layer prints it to stderr.
    """
    lines = [
        f"[+] Parsed Expr  : {info.py_expr}",
        f"[+] Width        : {info.width} bits",
        f"[+] Output Mode  : {info.inferred_base.name.lower()}",
        f"[+] Raw Int      : {info.raw_int}",
        f"[+] Unsigned Val : {info.unsigned}",
        "-" * 44,
    ]
    return "\n".join(lines)


# ── string XOR ────────────────────────────────────────────────────────────────

def _is_hex_literal(s: str) -> bool:
    """Return True if `s` looks like a hex literal (0x...)."""
    return bool(re.fullmatch(r"0[xX][0-9a-fA-F]+", s.strip()))


def _parse_hex_key(key_str: str) -> list[int]:
    """
    Parse a hex key like 0x41 or 0x4142 into a list of byte values.
    0x41   → [0x41]
    0x4142 → [0x41, 0x42]
    """
    raw_hex = key_str[2:]  # strip 0x prefix, e.g. "4142"
    if len(raw_hex) % 2 == 1:
        raw_hex = "0" + raw_hex
    return [int(raw_hex[i:i+2], 16) for i in range(0, len(raw_hex), 2)]


def xor_string(lhs: str, rhs: str) -> str:
    """
    XOR two operands where at least one side is a string.

    Supported forms:
      "hello" ^ 0x5     → XOR every char of "hello" against 0x05
      "hello" ^ 0x4142  → XOR chars cycling through [0x41, 0x42]
      "hello" ^ "world" → XOR each char of lhs against the corresponding
                               char of rhs (cycling if rhs is shorter)
      0x5 ^ "hello"     → same as "hello" ^ 0x5

    Returns the result as a hex integer string (e.g. "0x8d...").
    """
    lhs = lhs.strip()
    rhs = rhs.strip()

    # normalise: string always on left
    if _is_hex_literal(lhs) and not _is_hex_literal(rhs):
        lhs, rhs = rhs, lhs

    # lhs is definitely a plaintext string now
    # strip surrounding quotes if the user typed them
    for q in ('"', "'"):
        if lhs.startswith(q) and lhs.endswith(q):
            lhs = lhs[1:-1]
            break

    lhs_bytes = list(lhs.encode("latin-1"))

    if _is_hex_literal(rhs):
        # hex key — cycle through its bytes
        key_bytes = _parse_hex_key(rhs)
    else:
        # string key — strip quotes, cycle through its bytes
        for q in ('"', "'"):
            if rhs.startswith(q) and rhs.endswith(q):
                rhs = rhs[1:-1]
                break
        key_bytes = list(rhs.encode("latin-1"))

    if not key_bytes:
        raise ValueError("XOR key is empty")

    result_bytes = [
        lb ^ key_bytes[i % len(key_bytes)]
        for i, lb in enumerate(lhs_bytes)
    ]

    # pack result bytes into an integer
    result_int = 0
    for b in result_bytes:
        result_int = (result_int << 8) | b

    return hex(result_int)


# ── XOR expression detection ──────────────────────────────────────────────────

_RE_STRING_XOR = re.compile(
    r"""^
    \s*
    (?P<lhs>
        (?:\"[^\"]*\"|'[^']*'|[A-Za-z][A-Za-z0-9 _!@#$%^&*()\-=+\[\]{};:'",.<>?/\\|`~]*)
    )
    \s*\^\s*
    (?P<rhs>
        (?:\"[^\"]*\"|'[^']*'|0[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9 _!@#$%^&*()\-=+\[\]{};:'",.<>?/\\|`~]*)
    )
    \s*$""",
    re.VERBOSE,
)


def _looks_like_string_xor(expr: str) -> bool:
    """
    Return True if the expression is a string XOR rather than an integer XOR.
    We check: if there's a ^ and at least one side is not a pure integer/hex literal.
    """
    if "^" not in expr:
        return False
    # split on first ^
    parts = expr.split("^", 1)
    lhs, rhs = parts[0].strip(), parts[1].strip()
    # if both sides are valid integer literals, it's a normal numeric XOR
    def is_num_literal(s: str) -> bool:
        """Return True if `s` is a valid integer literal (decimal, hex, octal, binary)."""
        s = s.strip()
        try:
            int(s, 0)
            return True
        except (ValueError, TypeError):
            pass
        # custom suffixes
        if re.fullmatch(r"[0-9]+[oO]", s):
            return True
        if re.fullmatch(r"[01]+[bB]", s):
            return True
        return False
    return not (is_num_literal(lhs) and is_num_literal(rhs))


def _looks_like_plain_string(expr: str) -> bool:
    """
    Return True if `expr` is a bare or quoted plaintext string rather than a
    numeric/bitwise expression.  Quoted strings are always strings.  Unquoted
    strings are strings when they contain at least one letter that cannot be
    part of a numeric literal or operator and no numeric-only operator tokens.
    C equivalent: core_looks_like_plain_string()
    """
    s = expr.strip()
    # explicitly quoted → always a string
    if (s.startswith('"') and s.endswith('"')) or \
       (s.startswith("'") and s.endswith("'")):
        return True
    # contains any operator characters → not a plain string
    if re.search(r"[+\-*/<>|&~^]", s):
        return False
    # if it parses as a number, it's a number
    try:
        int(s, 0)
        return False
    except (ValueError, TypeError):
        pass
    if re.fullmatch(r"[0-9]+[oO]", s):
        return False
    if re.fullmatch(r"[01]+[bB]", s):
        return False
    # contains any letter → it's a string
    return bool(re.search(r"[a-zA-Z]", s))
 
 
def _strip_quotes(s: str) -> str:
    """Remove surrounding single or double quotes if present."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


# ── top-level process() ───────────────────────────────────────────────────────

def process(expr: str, spec: FormatSpec) -> tuple[str, str | None]:
    """
    Main entry point called by the CLI.
    Returns (output_string, verbose_string_or_None).
    C equivalent: core_process()
    """
    # ── ascii-encode: string → hex integer ───────────────────────────────────
    if spec.ascii_encode:
        raw = _strip_quotes(expr)
        # if the input is a numeric literal, evaluate it first then encode its bytes
        if not _looks_like_plain_string(raw):
            try:
                num = evaluate(raw)
                width = infer_width(translate_expr(raw), num, override=spec.width)
                n = mask_unsigned(num, width)
                byte_len = width // 8
                as_bytes = n.to_bytes(byte_len, "big")
                if spec.endian == Endian.LITTLE:
                    as_bytes = bytes(reversed(as_bytes))
                n = int.from_bytes(as_bytes, "big")
                width = byte_len * 8
                return _format_result(n, width, Base.HEX, spec), None
            except (ValueError, OverflowError):
                pass  # fall through to string encode
        n = ascii_encode(raw, endian=spec.endian)
        width = len(raw) * 8
        # endian is already baked into n; pass BIG to avoid double-reversing in _format_result
        fspec = copy.copy(spec)
        fspec.endian = Endian.BIG
        return _format_result(n, width, Base.HEX, fspec), None
 
    # ── plain string → encode then format ────────────────────────────────────
    if _looks_like_plain_string(expr):
        raw = _strip_quotes(expr)
        n   = ascii_encode(raw, endian=spec.endian)
        width = len(raw) * 8   # exact byte width — no rounding up
        fspec = copy.copy(spec)
        fspec.endian = Endian.BIG
        return _format_result(n, width, Base.HEX, fspec), None

    # ── string XOR detection ─────────────────────────────────────────────────
    if _looks_like_string_xor(expr):
        parts = expr.split("^", 1)
        hex_result = xor_string(parts[0].strip(), parts[1].strip())
        # hex_result is like "0x8d..." — now format it per spec
        n = int(hex_result, 16)
        width = spec.width or max(8, _next_pow2_bytes(n.bit_length() or 1))
        n = mask_unsigned(n, width)
        return _format_result(n, width, Base.HEX, spec), None

    # ── normal numeric expression ─────────────────────────────────────────────
    py_expr = translate_expr(expr)
    raw     = evaluate(expr)
    width   = infer_width(py_expr, raw, override=spec.width)
    n       = mask_unsigned(raw, width)

    inferred_base = detect_infix_base(expr)

    # ── ascii-decode: integer → string ───────────────────────────────────────
    if spec.ascii_decode:
        return fmt_ascii_decode(n, width, endian=spec.endian), None

    # ── verbose info ──────────────────────────────────────────────────────────
    verbose_str: str | None = None
    if spec.verbose:
        info = VerboseInfo(
            py_expr=py_expr,
            raw_int=raw,
            unsigned=n,
            width=width,
            inferred_base=inferred_base,
        )
        verbose_str = fmt_verbose(info)

    output = _format_result(n, width, inferred_base, spec)
    return output, verbose_str


def _format_result(n: int, width: int, inferred_base: Base, spec: FormatSpec) -> str:
    """Apply spec formatting to an already-evaluated, masked integer."""
    # ── show all (-A) ─────────────────────────────────────────────────────────
    if spec.show_all:
        rows = fmt_all(n, width, signed=spec.signed, upper=spec.upper, endian=spec.endian)
        max_key = max(len(k) for k in rows)
        return "\n".join(f"  {k:<{max_key}}  {v}" for k, v in rows.items())

    # ── ascii output (-a) ─────────────────────────────────────────────────────
    if spec.base == Base.ASC or spec.ascii_out:
        return fmt_ascii(n, width, endian=spec.endian)

    # ── escape sequence ───────────────────────────────────────────────────────
    if spec.escape:
        return fmt_escape(n, width, spec.endian, upper=spec.upper)

    # ── C array ───────────────────────────────────────────────────────────────
    if spec.c_array:
        return fmt_c_array(n, width, spec.endian, upper=spec.upper)

    # ── signed ────────────────────────────────────────────────────────────────
    if spec.signed:
        return fmt_signed(n, width)

    # ── grouped hex (-W / -w / -e little) ────────────────────────────────────
    # Only applies when no explicit non-hex base flag was given (-b/-d/-o/-a
    # take priority over grouping). Inferred base doesn't block grouping.
    if (spec.group_mode != GroupMode.NONE or spec.endian == Endian.LITTLE) \
            and spec.base not in (Base.BIN, Base.DEC, Base.OCT, Base.ASC):
        mode = spec.group_mode if spec.group_mode != GroupMode.NONE else GroupMode.BYTE
        gn   = spec.group_n
        return fmt_grouped(n, width, mode, gn, spec.endian, spec.spaces, spec.upper)

    # ── plain scalar output ───────────────────────────────────────────────────
    base = spec.base if spec.base is not None else inferred_base
    if base == Base.HEX:
        return fmt_hex(n, upper=spec.upper, prefix=not spec.no_prefix)
    if base == Base.DEC:
        return fmt_dec(n)
    if base == Base.OCT:
        return fmt_oct(n, prefix=not spec.no_prefix)
    if base == Base.BIN:
        # binary output never has a 0b prefix unless explicitly requested;
        # no_prefix has no additional effect here (already no prefix by default)
        return fmt_bin(n, spaces=spec.spaces, prefix=False)
    if base == Base.ASC:
        return fmt_ascii(n, width, endian=spec.endian)

    # fallback
    return fmt_hex(n, upper=spec.upper, prefix=not spec.no_prefix)
