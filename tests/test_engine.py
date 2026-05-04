"""
tests/test_engine.py
Tests for bitmath.core.engine — all business logic, no CLI.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from core.engine import (
    Base, GroupMode, Endian, FormatSpec,
    translate_expr, evaluate, infer_width, mask_unsigned,
    detect_infix_base, ascii_encode,
    fmt_hex, fmt_dec, fmt_oct, fmt_bin, fmt_signed,
    fmt_ascii_decode, fmt_grouped, fmt_escape, fmt_c_array, fmt_all,
    process,
)


# ── translate_expr ────────────────────────────────────────────────────────────

class TestTranslate:
    def test_octal_suffix(self):
        assert translate_expr("377o") == "0o377"

    def test_binary_suffix(self):
        assert translate_expr("11001100b") == "0b11001100"

    def test_hex_passthrough(self):
        assert translate_expr("0xdeadbeef") == "0xdeadbeef"

    def test_decimal_passthrough(self):
        assert translate_expr("255") == "255"

    def test_expression_with_suffixes(self):
        result = translate_expr("11110000b & 377o")
        assert "0b11110000" in result
        assert "0o377" in result

    def test_no_false_positive_in_hex(self):
        # 'b' in hex literal must not be treated as binary suffix
        expr = "0xdeadbeef"
        assert translate_expr(expr) == "0xdeadbeef"


# ── evaluate ──────────────────────────────────────────────────────────────────

class TestEvaluate:
    def test_hex_xor(self):
        assert evaluate("0xc6 ^ 0x79") == 0xbf

    def test_decimal_or(self):
        assert evaluate("198 | 121") == 255

    def test_shift_left(self):
        assert evaluate("0x01 << 4") == 0x10

    def test_shift_right(self):
        assert evaluate("0x80 >> 3") == 0x10

    def test_and(self):
        assert evaluate("0xff & 0x0f") == 0x0f

    def test_not_raw_negative(self):
        # ~0 is -1 in Python; masking happens later
        assert evaluate("~0") == -1

    def test_arithmetic(self):
        assert evaluate("0x10 + 0x20") == 0x30
        assert evaluate("0x40 * 2") == 0x80

    def test_parens(self):
        assert evaluate("(0x41 ^ 0x20) << 1") == 194

    def test_octal_suffix(self):
        assert evaluate("377o") == 0xff

    def test_binary_suffix(self):
        assert evaluate("11111111b") == 0xff

    def test_mixed_literals(self):
        assert evaluate("0xff & 11110000b") == 0xf0

    def test_64bit_no_overflow(self):
        assert evaluate("0xdeadbeefcafebabe") == 0xdeadbeefcafebabe

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            evaluate("import os")
        with pytest.raises(ValueError):
            evaluate("not_a_number")


# ── infer_width ───────────────────────────────────────────────────────────────

class TestInferWidth:
    def _w(self, expr):
        from core.engine import translate_expr, evaluate
        py = translate_expr(expr)
        r  = evaluate(expr)
        return infer_width(py, r)

    def test_8bit(self):   assert self._w("0xff") == 8
    def test_16bit(self):  assert self._w("0xffff") == 16
    def test_32bit(self):  assert self._w("0xdeadbeef") == 32
    def test_64bit(self):  assert self._w("0xdeadbeefcafebabe") == 64
    def test_decimal(self): assert self._w("255") == 8
    def test_override(self):
        py = translate_expr("0xff")
        assert infer_width(py, 0xff, override=32) == 32

    def test_invalid_override(self):
        with pytest.raises(ValueError):
            infer_width("0xff", 0xff, override=7)


# ── mask_unsigned ─────────────────────────────────────────────────────────────

class TestMaskUnsigned:
    def test_positive(self):
        assert mask_unsigned(0xdeadbeef, 32) == 0xdeadbeef

    def test_not_8bit(self):
        assert mask_unsigned(~0, 8) == 0xff

    def test_not_32bit(self):
        assert mask_unsigned(~0, 32) == 0xffffffff


# ── detect_infix_base ─────────────────────────────────────────────────────────

class TestDetectBase:
    def test_hex(self):   assert detect_infix_base("0xc6 ^ 0x79") == Base.HEX
    def test_dec(self):   assert detect_infix_base("198 | 121")   == Base.DEC
    def test_oct(self):   assert detect_infix_base("377o & 17o")  == Base.OCT
    def test_bin(self):   assert detect_infix_base("1010b | 5")   == Base.BIN
    def test_hex_wins(self):
        # hex literal appears first
        assert detect_infix_base("0xc6 ^ 121") == Base.HEX
    def test_dec_wins(self):
        assert detect_infix_base("198 ^ 0x79") == Base.DEC


# ── scalar formatters ─────────────────────────────────────────────────────────

class TestFmtHex:
    def test_basic(self):        assert fmt_hex(0xbf) == "0xbf"
    def test_upper(self):        assert fmt_hex(0xbf, upper=True) == "0XBF"
    def test_no_prefix(self):    assert fmt_hex(0xbf, prefix=False) == "bf"
    def test_zero(self):         assert fmt_hex(0) == "0x0"

class TestFmtBin:
    def test_no_leading_zeros(self):
        assert fmt_bin(0xd) == "1101"
    def test_no_leading_zeros_2(self):
        assert fmt_bin(0xbf) == "10111111"
    def test_spaces(self):
        assert fmt_bin(0xbf, spaces=True) == "1011 1111"
    def test_single_nibble_no_space(self):
        # 0xd fits in one nibble, spaces mode returns no space
        assert fmt_bin(0xd, spaces=True) == "1101"
    def test_two_nibbles_strips_leading_zero_group(self):
        # 0x1d = 0001 1101 → leading group is non-zero, keep it
        assert fmt_bin(0x1d, spaces=True) == "0001 1101"
    def test_zero(self):
        assert fmt_bin(0) == "0"


# ── grouped hex formatters ────────────────────────────────────────────────────

class TestFmtGrouped:
    def _g(self, n, width, mode, group_n, endian=Endian.BIG, spaces=False, upper=False):
        return fmt_grouped(n, width, mode, group_n, endian, spaces, upper)

    # byte groups (-W)
    def test_W1_no_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.BYTE, 1) == "deadbeef"
    def test_W1_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.BYTE, 1, spaces=True) == "de ad be ef"
    def test_W2_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.BYTE, 2, spaces=True) == "dead beef"
    def test_W4_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.BYTE, 4, spaces=True) == "deadbeef"

    # nibble groups (-w)
    def test_w1_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.NIBBLE, 1, spaces=True) == "d e a d b e e f"
    def test_w2_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.NIBBLE, 2, spaces=True) == "de ad be ef"
    def test_w4_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.NIBBLE, 4, spaces=True) == "dead beef"

    # endian
    def test_little_W1_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.BYTE, 1, Endian.LITTLE, True) == "ef be ad de"
    def test_little_W2_spaces(self):
        assert self._g(0xdeadbeef, 32, GroupMode.BYTE, 2, Endian.LITTLE, True) == "efbe adde"

    # 64-bit
    def test_64bit_W2_spaces(self):
        assert self._g(0xdeadbeefcafebabe, 64, GroupMode.BYTE, 2, spaces=True) == "dead beef cafe babe"

    # upper
    def test_upper(self):
        assert self._g(0xdeadbeef, 32, GroupMode.BYTE, 1, spaces=True, upper=True) == "DE AD BE EF"


# ── escape / c-array ──────────────────────────────────────────────────────────

class TestFmtEscape:
    def test_big_endian(self):
        assert fmt_escape(0xdeadbeef, 32, Endian.BIG) == r"\xde\xad\xbe\xef"
    def test_little_endian(self):
        assert fmt_escape(0xdeadbeef, 32, Endian.LITTLE) == r"\xef\xbe\xad\xde"
    def test_upper(self):
        assert fmt_escape(0xdeadbeef, 32, Endian.BIG, upper=True) == r"\xDE\xAD\xBE\xEF"

class TestFmtCArray:
    def test_basic(self):
        assert fmt_c_array(0xdeadbeef, 32, Endian.BIG) == "{ 0xde, 0xad, 0xbe, 0xef }"
    def test_little(self):
        assert fmt_c_array(0xdeadbeef, 32, Endian.LITTLE) == "{ 0xef, 0xbe, 0xad, 0xde }"
    def test_upper(self):
        assert fmt_c_array(0xdeadbeef, 32, Endian.BIG, upper=True) == "{ 0XDE, 0XAD, 0XBE, 0XEF }"


# ── process() integration ─────────────────────────────────────────────────────

def spec(**kwargs) -> FormatSpec:
    s = FormatSpec()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s

def p(expr, **kwargs):
    """Helper: call process() and return just the output string."""
    out, _ = process(expr, spec(**kwargs))
    return out

class TestProcess:
    # auto-infer
    def test_hex_in_hex_out(self):
        assert p("0xc6 ^ 0x79", ) == "0xbf"
    def test_dec_in_dec_out(self):
        assert p("198 | 121", ) == "255"
    def test_oct_in_oct_out(self):
        assert p("16o & 7o", ) == "0o6"
    def test_bin_in_bin_out(self):
        assert p("1100b ^ 1010b", ) == "110"

    # overrides
    def test_force_hex(self):
        assert p("198 | 121", base=Base.HEX) == "0xff"
    def test_force_dec(self):
        assert p("0xdeadbeef", base=Base.DEC) == "3735928559"
    def test_force_oct(self):
        assert p("255", base=Base.OCT) == "0o377"
    def test_force_bin(self):
        assert p("0xc6 ^ 0x79", base=Base.BIN) == "10111111"
    def test_force_bin_spaces(self):
        assert p("0xc6 ^ 0x79", base=Base.BIN, spaces=True) == "1011 1111"

    # grouped
    def test_W1_spaces(self):
        assert p("0xdeadbeef", group_mode=GroupMode.BYTE, group_n=1, spaces=True) == "de ad be ef"
    def test_W2_spaces(self):
        assert p("0xdeadbeef", group_mode=GroupMode.BYTE, group_n=2, spaces=True) == "dead beef"
    def test_w1_spaces(self):
        assert p("0xdeadbeef", group_mode=GroupMode.NIBBLE, group_n=1, spaces=True) == "d e a d b e e f"

    # endian
    def test_little_alone(self):
        assert p("0xdeadbeef", endian=Endian.LITTLE) == "efbeadde"
    def test_little_spaces(self):
        assert p("0xdeadbeef", endian=Endian.LITTLE, spaces=True) == "efbe adde"
    def test_W1_little_spaces(self):
        r, _ = process("0xdeadbeef", spec(group_mode=GroupMode.BYTE, group_n=1, endian=Endian.LITTLE, spaces=True))
        assert r == "ef be ad de"

    # escape / c-array
    def test_escape(self):
        assert p("0xdeadbeef", escape=True) == r"\xde\xad\xbe\xef"
    def test_c_array(self):
        assert p("0xdeadbeef", c_array=True) == "{ 0xde, 0xad, 0xbe, 0xef }"

    # upper / no-prefix
    def test_upper(self):
        assert p("0xdeadbeef", upper=True) == "0XDEADBEEF"
    def test_no_prefix(self):
        assert p("0xdeadbeef", no_prefix=True) == "deadbeef"

    # width override
    def test_width_override(self):
        r, _ = process("0xff", spec(
            group_mode=GroupMode.BYTE, group_n=1, spaces=True, width=32
        ))
        assert r == "00 00 00 ff"

    # 64-bit
    def test_64bit(self):
        assert p("0xdeadbeefcafebabe", ) == "0xdeadbeefcafebabe"
    def test_64bit_W2_spaces(self):
        r, _ = process("0xdeadbeefcafebabe", spec(group_mode=GroupMode.BYTE, group_n=2, spaces=True))
        assert r == "dead beef cafe babe"

    # real-world
    def test_rop_address(self):
        r, _ = process("0x08048460", spec(group_mode=GroupMode.BYTE, group_n=1, endian=Endian.LITTLE, spaces=True))
        assert r == "60 84 04 08"
    def test_port_bytes(self):
        r, _ = process("4444", spec(group_mode=GroupMode.BYTE, group_n=1, endian=Endian.LITTLE, spaces=True))
        assert r == "5c 11"

    # error
    def test_invalid_expr(self):
        with pytest.raises(ValueError):
            p("not_valid !!!")


# ── fmt_signed ────────────────────────────────────────────────────────────────

class TestFmtSigned:
    def test_0xff_8bit(self):
        assert fmt_signed(0xff, 8) == "-1"
    def test_0x80_8bit(self):
        assert fmt_signed(0x80, 8) == "-128"
    def test_0x7f_8bit(self):
        assert fmt_signed(0x7f, 8) == "127"
    def test_0x8000_16bit(self):
        assert fmt_signed(0x8000, 16) == "-32768"
    def test_positive_unchanged(self):
        assert fmt_signed(0x0f, 8) == "15"
    def test_max_positive_8bit(self):
        assert fmt_signed(0x7f, 8) == "127"


# ── ascii_encode / fmt_ascii_decode ───────────────────────────────────────────

class TestAscii:
    def test_encode_single_char(self):
        from core.engine import ascii_encode
        assert ascii_encode("A") == 0x41
    def test_encode_AAAA(self):
        from core.engine import ascii_encode
        assert ascii_encode("AAAA") == 0x41414141
    def test_encode_hello(self):
        from core.engine import ascii_encode
        assert ascii_encode("hello") == 0x68656c6c6f

    def test_decode_AAAA(self):
        assert fmt_ascii_decode(0x41414141, 32) == "AAAA"
    def test_decode_hello(self):
        assert fmt_ascii_decode(0x68656c6c6f, 40) == "hello"
    def test_decode_non_printable(self):
        # 0x00 is non-printable -> dot
        assert fmt_ascii_decode(0x0041, 16) == ".A"


# ── new process() modes ───────────────────────────────────────────────────────

class TestProcessNew:
    def test_ascii_decode(self):
        assert p("0x41414141", ascii_decode=True) == "AAAA"
    def test_ascii_encode(self):
        assert p("AAAA", ascii_encode=True) == "0x41414141"
    def test_ascii_encode_hello(self):
        assert p("hello", ascii_encode=True) == "0x68656c6c6f"
    def test_signed_hex_in(self):
        assert p("0xff", signed=True, base=Base.DEC) == "-1"
    def test_signed_8000(self):
        assert p("0x8000", signed=True, base=Base.DEC, width=16) == "-32768"
    def test_signed_decimal_expr(self):
        assert p("-4 + -3", signed=True) == "-7"
    def test_overflow_simulation(self):
        assert p("0xffffffff + 1", width=32) == "0x0"
    def test_verbose_returns_info(self):
        _, verbose = process("0xc6 ^ 0x79", spec())
        assert verbose is None  # verbose=False by default
    def test_verbose_on(self):
        _, verbose = process("0xc6 ^ 0x79", spec(verbose=True))
        assert verbose is not None
        assert "0xc6 ^ 0x79" in verbose
        assert "8 bits" in verbose
    def test_show_all_has_ascii_row(self):
        out, _ = process("0x41414141", spec(show_all=True))
        assert "ascii" in out
        assert "AAAA" in out
    def test_show_all_has_signed_row(self):
        out, _ = process("0xff", spec(show_all=True, signed=True))
        assert "signed" in out
        assert "-1" in out
