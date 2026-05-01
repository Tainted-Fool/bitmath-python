"""
bitmath.core.engine
~~~~~~~~~~~~~~~~~~~
Pure business logic: expression evaluation, width inference, and all
formatting.  No argparse, no sys.argv, no I/O — only functions that
take plain Python values and return plain Python values.

C-portability contract
~~~~~~~~~~~~~~~~~~~~~~
Every function in this module has a direct C equivalent.  The mapping is:

  Python function          C function (future)
  ─────────────────────────────────────────────
  translate_expr()         bm_translate_expr()
  evaluate()               bm_evaluate()        (wraps mpz or __int128)
  infer_width()            bm_infer_width()
  mask_unsigned()          bm_mask_unsigned()
  detect_infix_base()      bm_detect_infix_base()
  fmt_*()                  bm_fmt_*()

Keep this file free of:
  - argparse / sys / os / subprocess
  - print() calls
  - Any I/O whatsoever

The only acceptable imports are: re, math, and the standard library types.
"""

from __future__ import annotations
import re
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ── types ─────────────────────────────────────────────────────────────────────

class Base(Enum):
    HEX = auto()
    DEC = auto()
    OCT = auto()
    BIN = auto()

class GroupMode(Enum):
    NONE   = auto()   # plain scalar output
    BYTE   = auto()   # -W: group by N bytes
    NIBBLE = auto()   # -w: group by N nibbles

class Endian(Enum):
    BIG    = auto()
    LITTLE = auto()

@dataclass
class FormatSpec:
    """All display options in one place.  Mirrors what the CLI parses."""
    base:        Optional[Base]  = None   # None = auto-infer
    group_mode:  GroupMode       = GroupMode.NONE
    group_n:     int             = 2
    endian:      Endian          = Endian.BIG
    spaces:      bool            = False
    upper:       bool            = False
    no_prefix:   bool            = False   # strip 0x / 0b / 0o
    escape:      bool            = False   # \xNN output
    c_array:     bool            = False   # { 0xNN, ... }
    show_all:    bool            = False   # print all bases
    width:       Optional[int]   = None    # explicit bit-width override

@dataclass
class EvalResult:
    """Everything produced by a single expression evaluation."""
    unsigned:    int             # masked unsigned value
    width:       int             # inferred or overridden bit-width (8/16/32/64/...)
    inferred_base: Base          # base detected from first literal


# ── literal translation ───────────────────────────────────────────────────────
# Converts our custom suffixes to Python-native literals so eval() works.
#
# Custom syntax  →  Python syntax
#   377o         →  0o377
#   11001100b    →  0b11001100
#   0xDEAD       →  (already valid)
#   255          →  (already valid)
#
# C note: bm_translate_expr() does the same rewriting with two regex passes
# on a stack-allocated char buffer.

_RE_OCT_SUFFIX = re.compile(r'(?<![0-9a-fA-F_])([0-9]+)[oO](?![0-9a-fA-F_])')
_RE_BIN_SUFFIX = re.compile(r'(?<![0-9a-fA-F_])([01]+)[bB](?![0-9a-fA-F_])')

def translate_expr(expr: str) -> str:
    """Rewrite custom literal suffixes to Python-native form."""
    expr = _RE_OCT_SUFFIX.sub(r'0o\1', expr)
    expr = _RE_BIN_SUFFIX.sub(r'0b\1', expr)
    return expr


# ── safe evaluation ───────────────────────────────────────────────────────────
# Uses a whitelist of allowed names (empty) and disables builtins.
# Python's arbitrary-precision integers mean no overflow is possible.
#
# C note: bm_evaluate() will use a recursive-descent parser + GMP mpz_t,
# supporting the same operators: & | ^ ~ << >> + - * // % ( )

_SAFE_GLOBALS: dict = {"__builtins__": {}}

def evaluate(expr: str) -> int:
    """
    Evaluate a bitwise/arithmetic expression string.
    Returns a raw Python int (may be negative, e.g. from ~).
    Raises ValueError on invalid input.
    """
    py_expr = translate_expr(expr)
    try:
        result = eval(py_expr, _SAFE_GLOBALS)  # noqa: S307
    except Exception as exc:
        raise ValueError(f"invalid expression: {expr!r}") from exc
    if not isinstance(result, int):
        raise ValueError(f"expression must evaluate to an integer, got {type(result).__name__}")
    return result


# ── width inference ───────────────────────────────────────────────────────────
# Rules (applied in order, first match wins):
#   1. Explicit --width override → use it directly
#   2. Find all numeric literals in the translated expression; take the widest
#   3. If the result is wider than any literal, use the result's width
#   4. Round up to the nearest power-of-2 byte boundary, minimum 8 bits
#
# C note: bm_infer_width() iterates the token stream from the parser.

_RE_LITERALS = re.compile(
    r'0[xX][0-9a-fA-F]+'   # hex
    r'|0[bB][01]+'          # binary
    r'|0[oO][0-7]+'         # octal
    r'|\b\d+\b'             # decimal
)

def _next_pow2_bytes(bits: int, minimum: int = 8) -> int:
    """Round `bits` up to the next power-of-2 bit count (min 8)."""
    w = minimum
    while w < bits:
        w *= 2
    return w

def infer_width(py_expr: str, result: int, override: Optional[int] = None) -> int:
    """
    Return the display bit-width for `result` given the expression's literals.
    `py_expr` must already be translated (0o / 0b prefixes, not o/b suffixes).
    """
    if override is not None:
        if override not in (8, 16, 32, 64, 128, 256):
            raise ValueError(f"--width must be 8, 16, 32, 64, 128, or 256; got {override}")
        return override

    max_literal_bits = 0
    for m in _RE_LITERALS.finditer(py_expr):
        val = int(m.group(0), 0)
        max_literal_bits = max(max_literal_bits, val.bit_length())

    # For negative results (e.g. ~x before masking), bit_length() behaves
    # oddly; take the absolute value + 1 as a conservative upper bound.
    res_bits = result.bit_length() if result >= 0 else ((-result - 1).bit_length() + 1)
    needed = max(max_literal_bits, res_bits, 1)
    return _next_pow2_bytes(needed)

def mask_unsigned(value: int, width: int) -> int:
    """Mask `value` to `width` bits, producing an unsigned integer."""
    return value & ((1 << width) - 1)


# ── base detection ────────────────────────────────────────────────────────────
# Scans tokens left-to-right; the first recognised literal sets the base.
# Operators and whitespace are skipped.

_RE_FIRST_LITERAL = re.compile(
    r'0[xX][0-9a-fA-F]+'   # hex   (check before plain int)
    r'|0[bB][01]+'          # binary (0b prefix — post-translation)
    r'|0[oO][0-7]+'         # octal  (0o prefix — post-translation)
    r'|[01]+[bB]'           # binary (original b-suffix, pre-translation)
    r'|[0-9]+[oO]'          # octal  (original o-suffix, pre-translation)
    r'|\b[0-9]+\b'          # decimal
)

def detect_infix_base(expr: str) -> Base:
    """
    Return the Base implied by the first literal token in `expr`.
    Falls back to DEC if nothing is recognised.
    """
    m = _RE_FIRST_LITERAL.search(expr)
    if not m:
        return Base.DEC
    tok = m.group(0)
    if tok.startswith(('0x', '0X')):
        return Base.HEX
    if tok.startswith(('0b', '0B')) or tok.endswith(('b', 'B')):
        return Base.BIN
    if tok.startswith(('0o', '0O')) or tok.endswith(('o', 'O')):
        return Base.OCT
    return Base.DEC


# ── scalar formatters ─────────────────────────────────────────────────────────

def fmt_hex(n: int, upper: bool = False, prefix: bool = True) -> str:
    """Format as hex.  `prefix` controls the 0x leader."""
    h = format(n, 'X' if upper else 'x')
    return (('0X' if upper else '0x') + h) if prefix else h

def fmt_dec(n: int) -> str:
    return str(n)

def fmt_oct(n: int, prefix: bool = True) -> str:
    o = format(n, 'o')
    return ('0o' + o) if prefix else o

def fmt_bin(n: int, spaces: bool = False) -> str:
    """
    Binary without leading zeros.  With `spaces`, nibble-groups are
    space-separated; a leading all-zero nibble is stripped.
    """
    raw = format(n, 'b') if n > 0 else '0'
    if not spaces:
        return raw
    # Pad to nibble boundary
    pad = (4 - len(raw) % 4) % 4
    raw = '0' * pad + raw
    groups = [raw[i:i+4] for i in range(0, len(raw), 4)]
    # Drop leading zero-nibble (it was only padding)
    while len(groups) > 1 and groups[0] == '0000':
        groups.pop(0)
    return ' '.join(groups)


# ── grouped hex formatters ────────────────────────────────────────────────────

def _nibble_list(n: int, width: int, upper: bool = False) -> list[str]:
    """Return a flat list of `width//4` hex nibble chars, MSB-first."""
    fmt = f'0{width // 4}{"X" if upper else "x"}'
    return list(format(n, fmt))

def _apply_endian(nibbles: list[str], endian: Endian) -> list[str]:
    """Reverse at byte granularity for little-endian."""
    if endian == Endian.BIG:
        return nibbles
    byte_count = len(nibbles) // 2
    pairs = [nibbles[i*2:(i+1)*2] for i in range(byte_count)]
    pairs.reverse()
    return [c for pair in pairs for c in pair]

def fmt_grouped(
    n: int,
    width: int,
    mode: GroupMode,
    group_n: int,
    endian: Endian,
    spaces: bool,
    upper: bool = False,
) -> str:
    """
    Byte-grouped (-W) or nibble-grouped (-w) hex output.

    mode=BYTE:   group_n is in bytes  → chunk = group_n * 2 nibbles
    mode=NIBBLE: group_n is in nibbles → chunk = group_n nibbles
    """
    nibbles = _nibble_list(n, width, upper)
    nibbles = _apply_endian(nibbles, endian)
    chunk = group_n * 2 if mode == GroupMode.BYTE else group_n
    groups = [''.join(nibbles[i:i+chunk]) for i in range(0, len(nibbles), chunk)]
    sep = ' ' if spaces else ''
    return sep.join(groups)


# ── escape / C-array formatters ───────────────────────────────────────────────

def fmt_escape(n: int, width: int, endian: Endian, upper: bool = False) -> str:
    r"""Format as \xNN\xNN... escape sequence."""
    nibbles = _nibble_list(n, width, upper)
    nibbles = _apply_endian(nibbles, endian)
    pairs = [''.join(nibbles[i:i+2]) for i in range(0, len(nibbles), 2)]
    return ''.join(f'\\x{p}' for p in pairs)

def fmt_c_array(n: int, width: int, endian: Endian, upper: bool = False) -> str:
    """Format as a C byte-array literal: { 0xde, 0xad, 0xbe, 0xef }"""
    nibbles = _nibble_list(n, width, upper)
    nibbles = _apply_endian(nibbles, endian)
    pairs = [''.join(nibbles[i:i+2]) for i in range(0, len(nibbles), 2)]
    prefix = '0X' if upper else '0x'
    elems = ', '.join(f'{prefix}{p}' for p in pairs)
    return '{ ' + elems + ' }'


# ── "show all" formatter ──────────────────────────────────────────────────────

def fmt_all(result: EvalResult, upper: bool = False) -> dict[str, str]:
    """
    Return an ordered dict of all representations.
    Used by --all / -a mode.
    """
    n, w = result.unsigned, result.width
    return {
        'hex':    fmt_hex(n, upper=upper),
        'dec':    fmt_dec(n),
        'oct':    fmt_oct(n),
        'bin':    fmt_bin(n, spaces=True),
        'bytes':  fmt_grouped(n, w, GroupMode.BYTE, 1, Endian.BIG, spaces=True, upper=upper),
        'width':  f'{w}-bit',
    }


# ── main entry point for the CLI layer ───────────────────────────────────────

def process(expr: str, spec: FormatSpec) -> str:
    """
    Evaluate `expr` and format the result according to `spec`.
    Returns a single string ready to print.
    Raises ValueError on bad input.

    This is the only function the CLI layer needs to call.
    C equivalent: bm_process(const char *expr, const BmFormatSpec *spec, char *out, size_t outlen)
    """
    py_expr   = translate_expr(expr)
    raw       = evaluate(expr)
    width     = infer_width(py_expr, raw, spec.width)
    unsigned  = mask_unsigned(raw, width)
    inferred  = detect_infix_base(expr)
    base      = spec.base if spec.base is not None else inferred

    result = EvalResult(unsigned=unsigned, width=width, inferred_base=inferred)

    # --all overrides everything else
    if spec.show_all:
        rows = fmt_all(result, upper=spec.upper)
        width_val = rows.pop('width')
        col = max(len(k) for k in rows)
        lines = [f"  {k:<{col}}  {v}" for k, v in rows.items()]
        lines.append(f"  {'width':<{col}}  {width_val}")
        return '\n'.join(lines)

    # escape / c-array modes — endian applies, but no visual grouping
    if spec.escape:
        return fmt_escape(unsigned, width, spec.endian, spec.upper)
    if spec.c_array:
        return fmt_c_array(unsigned, width, spec.endian, spec.upper)

    # grouped hex modes (-W / -w)
    if spec.group_mode != GroupMode.NONE:
        return fmt_grouped(
            unsigned, width, spec.group_mode, spec.group_n,
            spec.endian, spec.spaces, spec.upper,
        )

    # -e little alone → byte-grouped with default group_n
    if spec.endian == Endian.LITTLE and spec.group_mode == GroupMode.NONE:
        return fmt_grouped(
            unsigned, width, GroupMode.BYTE, spec.group_n,
            spec.endian, spec.spaces, spec.upper,
        )


    # scalar modes
    prefix = not spec.no_prefix
    if base == Base.HEX:
        return fmt_hex(unsigned, upper=spec.upper, prefix=prefix)
    if base == Base.DEC:
        return fmt_dec(unsigned)
    if base == Base.OCT:
        return fmt_oct(unsigned, prefix=prefix)
    if base == Base.BIN:
        return fmt_bin(unsigned, spaces=spec.spaces)

    return fmt_hex(unsigned, upper=spec.upper, prefix=prefix)  # fallback
