"""bitmath.core — public API for the evaluation and formatting engine."""

from .engine import (
    Base,
    GroupMode,
    Endian,
    FormatSpec,
    EvalResult,
    process,
    # lower-level exports for direct use / testing
    translate_expr,
    evaluate,
    infer_width,
    mask_unsigned,
    detect_infix_base,
    fmt_hex,
    fmt_dec,
    fmt_oct,
    fmt_bin,
    fmt_grouped,
    fmt_escape,
    fmt_c_array,
    fmt_all,
    fmt_signed,
    fmt_ascii_decode,
    ascii_encode,
    fmt_verbose
)

__all__ = [
    "Base", "GroupMode", "Endian", "FormatSpec", "EvalResult",
    "process",
    "translate_expr", "evaluate", "infer_width", "mask_unsigned",
    "detect_infix_base",
    "fmt_hex", "fmt_dec", "fmt_oct", "fmt_bin",
    "fmt_grouped", "fmt_escape", "fmt_c_array", "fmt_all",
]
