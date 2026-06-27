# bitmath

An exploit-dev friendly bitwise calculator for the command line.

```
bitmath "0xc6 ^ 0x79"                      ->  0xbf
bitmath -A "0x41414141"                    ->  all representations (hex/dec/oct/bin/bytes/ascii)
bitmath -a "0x41414141"                    ->  AAAA   (ascii output format)
bitmath -D "0x41414141"                    ->  AAAA   (decode integer to ASCII)
bitmath -n "hello"                         ->  0x68656c6c6f  (encode ASCII to hex)
bitmath "hello ^ 0x5"                      ->  XOR every byte of "hello" against 0x05
bitmath "hello ^ world"                    ->  per-char XOR against "world"
bitmath "hello world ^ 0x4142"             ->  cycle key across all chars incl. space
bitmath -t -d "0xff"                       ->  -1     (signed two's complement)
bitmath -S 32 "0xffffffff + 1"             ->  0x0    (32-bit overflow simulation)
bitmath -W 1 -s -e little "0xdeadbeef"     ->  ef be ad de
bitmath -E "0xdeadbeef"                    ->  \xde\xad\xbe\xef
bitmath --c-array "0xdeadbeef"             ->  { 0xde, 0xad, 0xbe, 0xef }
echo "0xff & 0x0f" | bitmath               ->  0xf   (stdin)
```

---

## Installation

```bash
git clone https://github.com/Tainted-Fool/bitmath-python.git
cd bitmath-python
chmod +x bitmath
./bitmath "0xdeadbeef"

# optional: put on your PATH
ln -s bitmath ~/.local/bin/bitmath
```

**Requirements:** Python 3.8+. No third-party packages.

---

## Project Structure

```
bitmath-py/
├── bitmath              # executable entry point  (chmod +x this)
├── core/
│   ├── __init__.py      # public API exports
│   └── engine.py        # ALL business logic — zero I/O, zero CLI
├── cli/
│   └── bitmath.py       # argument parsing + I/O only, calls core.process()
└── tests/
    └── test_engine.py   # tests covering every function in core/
```

`core/` and `cli/` are deliberately separated. Every function in `core/engine.py`
documents its future C equivalent — when a C port is written, only `cli/`
changes and the engine is a direct translation target.

---

## Usage

```
bitmath [flags] "expression"
```

Quote expressions to protect `|`, `~`, `<`, `>` from the shell.
Omit the expression to read from **stdin**.

---

## Operators

| Operator    | Meaning       | Example                       | Result  |
|-------------|---------------|-------------------------------|---------|
| `&`         | AND           | `bitmath "0xff & 0x0f"`       | `0xf`   |
| `\|`        | OR            | `bitmath "0xf0 \| 0x0f"`     | `0xff`  |
| `^`         | XOR           | `bitmath "0xaa ^ 0x55"`       | `0xff`  |
| `~`         | NOT (bitwise) | `bitmath "~0x00 & 0xff"`      | `0xff`  |
| `<<`        | Shift left    | `bitmath "0x01 << 4"`         | `0x10`  |
| `>>`        | Shift right   | `bitmath "0x80 >> 3"`         | `0x10`  |
| `+` `-` `*` | Arithmetic    | `bitmath "0x10 + 0x20"`       | `0x30`  |

Parentheses work: `bitmath "(0x41 ^ 0x20) << 1"`.

> **`~` (NOT) note:** Python's `~` produces a negative value on arbitrary-precision
> integers. Mask to your intended width: `~0x00 & 0xff` → `0xff`.

---

## Literal Formats

Mix any of these in a single expression:

| Format    | Syntax       | Example       |
|-----------|--------------|---------------|
| Hex       | `0x` prefix  | `0xdeadbeef`  |
| Decimal   | plain int    | `255`         |
| Octal     | trailing `o` | `377o`        |
| Binary    | trailing `b` | `11111111b`   |

```bash
bitmath "0xff & 11110000b"    ->  0xf0
bitmath "377o ^ 0x0f"         ->  0o360
bitmath "1010b | 0101b"       ->  1111
```

---

## Output Format Auto-Inference

Output mirrors the **first literal** in your expression:

| Input type    | Default output  |
|---------------|-----------------|
| `0x...`       | hex (`0xbf`)    |
| plain integer | decimal (`191`) |
| `...o`        | octal (`0o6`)   |
| `...b`        | binary (`1111`) |

```bash
bitmath "0xc6 ^ 121"    ->  0xbf   (hex wins, appears first)
bitmath "198 ^ 0x79"    ->  191    (decimal wins, appears first)
```

Override with `-x` / `-d` / `-o` / `-b` / `-a`.

---

## Output Override Flags

| Flag | Output    | Example                      | Result       |
|------|-----------|------------------------------|--------------|
| `-x` | hex       | `bitmath -x "198 \| 121"`   | `0xff`       |
| `-d` | decimal   | `bitmath -d "0xdeadbeef"`    | `3735928559` |
| `-o` | octal     | `bitmath -o "255"`           | `0o377`      |
| `-b` | binary    | `bitmath -b "0xc6 ^ 0x79"`  | `10111111`   |
| `-a` | ascii     | `bitmath -a "0x41414141"`   | `AAAA`       |

Binary output has no leading zeros and no spaces by default. Add `-s` for nibble-grouped spaces.
ASCII output renders printable bytes directly; non-printable bytes appear as `.`.

---

## String XOR

The `^` operator works on plaintext strings, not just integers. At least one
side of the expression must be a non-numeric string for this mode to activate.
Numeric-only expressions (`0xc6 ^ 0x79`, `198 ^ 121`) are unaffected.

### Forms

| Expression                   | Behaviour                                              |
|------------------------------|--------------------------------------------------------|
| `"hello ^ 0x5"`              | XOR every byte of `hello` against `0x05`               |
| `"hello ^ 0x4142"`           | Cycle key bytes `[0x41, 0x42]` across `hello`          |
| `"hello ^ world"`            | Per-char XOR; key cycles if shorter than plaintext     |
| `"hello world ^ 0x4142"`     | Spaces included; key still cycles                      |
| `"0x5 ^ hello"`              | Operand order is normalised — same result              |

The result is always formatted as a hex integer. Apply any output flag on top:

```bash
bitmath "hello ^ 0x20"                    ->  0x48656c6c6f
bitmath -W 1 -s "hello ^ 0x20"            ->  48 65 6c 6c 6f
bitmath -E "hello ^ 0x20" 2>/dev/null     # combine with escape output manually
```

### Examples

```bash
# XOR each byte of "hello" against 0x05
bitmath "hello ^ 0x5"                     ->  0x6d6069696a

# Cycle a two-byte key across "hello"
bitmath "hello ^ 0x4142"                  ->  0x29272d2e2e

# Per-character string XOR
bitmath "hello ^ world"                   ->  0x1f0a1e000b

# String with space, cycling key
bitmath "hello world ^ 0x4142"            ->  0x29272d2e2e62362d332e25

# Reverse key order — same result
bitmath "0x4142 ^ hello"                  ->  0x29272d2e2e
```

---

## Grouped Hex Output

### `-W [N]` — byte groups
Groups output in chunks of **N bytes** (= N×2 hex chars). Default N = 2.

```bash
bitmath -W 1 "0xdeadbeef"          ->  deadbeef      # compact / paste-ready
bitmath -W 1 -s "0xdeadbeef"       ->  de ad be ef
bitmath -W 2 -s "0xdeadbeef"       ->  dead beef
bitmath -W 4 -s "0xdeadbeef"       ->  deadbeef
```

### `-w [N]` — nibble groups
Groups output in chunks of **N nibbles** (= N hex chars). Default N = 2.

```bash
bitmath -w 1 -s "0xdeadbeef"       ->  d e a d b e e f
bitmath -w 2 -s "0xdeadbeef"       ->  de ad be ef
bitmath -w 4 -s "0xdeadbeef"       ->  dead beef
```

`-W 1` and `-w 2` produce identical output — 1 byte = 2 nibbles.

---

## Spacing Flag

```
-s / --spaces    add spaces between groups  (works with -b, -W, -w)
```

Without `-s`, groups are concatenated — paste-ready for payloads.
With `-s`, space-separated — readable in terminal output.

---

## Endianness

```
-e big      big-endian byte order (default)
-e little   reverse byte order before display; implies -W if no group flag given
```

```bash
bitmath -e little "0xdeadbeef"             ->  efbeadde
bitmath -e little -s "0xdeadbeef"          ->  efbe adde        # default group=2
bitmath -W 1 -s -e little "0xdeadbeef"     ->  ef be ad de
bitmath -W 2 -s -e little "0xdeadbeef"     ->  efbe adde
```

---

## Display Options

| Flag              | Effect                                   | Example output   |
|-------------------|------------------------------------------|------------------|
| `-u` / `--upper`  | Uppercase hex digits                     | `0XDEADBEEF`     |
| `-P` / `--no-prefix` | Omit `0x` / `0o` / `0b` prefix       | `deadbeef`       |
| `-S` / `--size` BITS | Force display width + overflow sim    | see below        |

```bash
bitmath -x -u "0xdeadbeef"             ->  0XDEADBEEF
bitmath -x -P "0xdeadbeef"             ->  deadbeef
bitmath -S 32 "0xffffffff + 1"         ->  0x0       (32-bit overflow)
bitmath -W 1 -s -S 64 "0xff"           ->  00 00 00 00 00 00 00 ff
```

---

## Special Output Modes

### `-A` / `--all` — show everything at once
```bash
bitmath -A "0x41414141"
  hex    0x41414141
  dec    1094795585
  oct    0o10120240501
  bin    0100 0001 0100 0001 0100 0001 0100 0001
  bytes  41 41 41 41
  ascii  AAAA
  width  32-bit
```

Add `-t` to include a signed row:
```bash
bitmath -A -t "0xff"
  hex     0xff
  dec     255
  oct     0o377
  bin     1111 1111
  bytes   ff
  ascii   .
  signed  -1
  width   8-bit
```

### `-a` — ASCII output format
Renders the integer's bytes as ASCII characters. Non-printable bytes appear as `.`.
Strips width-padding bytes so values like `0x68656c6c6f` display cleanly.

```bash
bitmath -a "0x41414141"                ->  AAAA
bitmath -a "0x68656c6c6f"              ->  hello
bitmath -a "0x4865"                    ->  He
bitmath -a "0xc3"                      ->  .      (non-printable)
```

### `-D` / `--decode` — integer to ASCII string
Decodes each byte of the integer to its ASCII character using the full inferred
width (preserving leading zero bytes). Non-printable bytes render as `.`.

> **Alias:** `--ascii-decode` still works for backwards compatibility.

```bash
bitmath -D "0x41414141"                ->  AAAA
bitmath -D "0x4865"                    ->  He
bitmath -D "0x0041"                    ->  .A     (leading zero byte preserved)
```

### `-n` / `--encode` — ASCII string to hex integer
Encodes each character of the string as its hex byte value (big-endian).

> **Alias:** `--ascii-encode` still works for backwards compatibility.

```bash
bitmath -n "AAAA"                      ->  0x41414141
bitmath -n "hello"                     ->  0x68656c6c6f
bitmath -n -P "NOP"                    ->  4e4f50
```

### `-t` / `--signed` — two's complement signed interpretation
Interprets the result as a signed integer of the inferred (or forced) bit-width.
Only meaningful for decimal output — combine with `-d` or use on decimal expressions.

```bash
bitmath -t -d "0xff"                   ->  -1      (8-bit signed)
bitmath -t -d "0x80"                   ->  -128    (8-bit min)
bitmath -t -d -S 16 "0x8000"           ->  -32768  (16-bit min)
bitmath -t "-4 + -3"                   ->  -7      (decimal in -> decimal out)
```

### `-S` / `--size` BITS — forced width / overflow simulation
Forces the bit-width for masking. Simulates hardware integer overflow naturally:
```bash
bitmath -S 8  "0xff + 1"              ->  0x0     (8-bit overflow)
bitmath -S 16 "0xffff + 1"            ->  0x0     (16-bit overflow)
bitmath -S 32 "0xffffffff + 1"        ->  0x0     (32-bit overflow)
bitmath -W 1 -s -S 64 "0xff"          ->  00 00 00 00 00 00 00 ff
```

### `-E` / `--escape` — `\x` escape sequence
```bash
bitmath -E "0xdeadbeef"                ->  \xde\xad\xbe\xef
bitmath -E -e little "0xdeadbeef"      ->  \xef\xbe\xad\xde
bitmath -E -u "0xdeadbeef"             ->  \xDE\xAD\xBE\xEF
```

### `--c-array` — C byte-array literal
```bash
bitmath --c-array "0xdeadbeef"             ->  { 0xde, 0xad, 0xbe, 0xef }
bitmath --c-array -e little "0xdeadbeef"   ->  { 0xef, 0xbe, 0xad, 0xde }
bitmath --c-array -u "0xdeadbeef"          ->  { 0XDE, 0XAD, 0XBE, 0XEF }
```

### `-v` / `--verbose` — show parse diagnostics
Prints intermediate steps to stderr before the result:
```bash
bitmath -v "0xc6 ^ 0x79"
[+] Parsed Expr  : 0xc6 ^ 0x79
[+] Width        : 8 bits
[+] Output Mode  : hex
[+] Raw Int      : 191
[+] Unsigned Val : 191
--------------------------------------------
0xbf
```

---

## Stdin Support

```bash
echo "0xc6 ^ 0x79"  | bitmath              ->  0xbf
echo "0xdeadbeef"   | bitmath -W 1 -s      ->  de ad be ef
echo "0xff & 0x0f"  | bitmath -b           ->  1111
```

---

## Width Inference

The display width (8/16/32/64/...) is inferred automatically from the widest
literal in your expression, rounded up to the nearest power-of-2 byte boundary.
Override with `-S`.

```bash
bitmath -W 1 -s "0xff"                     ->  ff
bitmath -W 1 -s "0xffff"                   ->  ff ff
bitmath -W 1 -s "0xdeadbeef"               ->  de ad be ef
bitmath -W 1 -s "0xdeadbeefcafebabe"       ->  de ad be ef ca fe ba be
bitmath -W 1 -s -S 32 "0xff"               ->  00 00 00 ff
```

---

## Real-World Examples

**XOR key recovery**
```bash
bitmath "0xc6 ^ 0x79"                        ->  0xbf
```

**Identify bytes in a register value**
```bash
bitmath -A "0x41414141"
# shows hex, dec, oct, bin, bytes, ascii ("AAAA"), width all at once
```

**Quick ASCII check on a value**
```bash
bitmath -a "0x41414141"                      ->  AAAA
```

**XOR-decrypt a short ciphertext against a known key byte**
```bash
bitmath "cipher ^ 0x42"                      ->  per-byte XOR result as hex
```

**XOR two strings character-by-character**
```bash
bitmath "hello ^ world"                      ->  0x1f0a1e000b
```

**XOR with a multi-byte cycling key**
```bash
bitmath "hello world ^ 0x4142"               ->  0x29272d2e2e62362d332e25
```

**Encode a string for a shellcode payload**
```bash
bitmath -n "//sh"                            ->  0x2f2f7368
bitmath -E "0x2f2f7368"                      ->  \x2f\x2f\x73\x68
```

**Build a shellcode byte sequence**
```bash
bitmath -W 1 -s "0xdeadbeef"               ->  de ad be ef
bitmath --c-array "0xdeadbeef"             ->  { 0xde, 0xad, 0xbe, 0xef }
```

**Little-endian ROP chain address**
```bash
bitmath -W 1 -s -e little "0x08048460"     ->  60 84 04 08
```

**Port number to wire bytes**
```bash
bitmath -W 1 -s -e little "4444"           ->  5c 11
```

**Simulate a 32-bit integer overflow**
```bash
bitmath -S 32 "0xffffffff + 1"             ->  0x0
bitmath -S 32 "0x7fffffff + 1"             ->  0x80000000
```

**Interpret a value as signed**
```bash
bitmath -t -d "0x80000000" -S 32           ->  -2147483648
```

**Check a bitmask**
```bash
bitmath -b -s "0b11001100 & 0b10101010"    ->  1000 1000
```

**Flag extraction (bits 4-7)**
```bash
bitmath -b -s "0xAB & 0xF0"                ->  1010 0000
```

**Rotate right 4 bits (32-bit)**
```bash
bitmath -b -s "((0xdeadbeef >> 4) | (0xdeadbeef << 28)) & 0xffffffff"
->  1111 1101 1110 1010 1101 1011 1110 1110
```

### Loop Example

Loop through each byte value and XOR against `0x66`:

```bash
for i in {0..255}; do
    printf "%02x -> %02x\n" $i $(bitmath "$i ^ 0x66")
done
```

---

## Flag Reference

| Flag                    | Meaning                                                            |
|-------------------------|--------------------------------------------------------------------|
| `-x`                    | Force hex output                                                   |
| `-d`                    | Force decimal output                                               |
| `-o`                    | Force octal output                                                 |
| `-b`                    | Force binary output (no leading zeros)                             |
| `-a`                    | Force ASCII output (printable bytes; `.` for non-printable)        |
| `-W [N]`                | Byte-grouped hex, N bytes per group (default 2)                    |
| `-w [N]`                | Nibble-grouped hex, N nibbles per group (default 2)                |
| `-s` / `--spaces`       | Add spaces between groups                                          |
| `-e big\|little`        | Byte order (little implies -W if unset)                            |
| `-S` / `--size` BITS    | Force bit-width / overflow simulation (8, 16, 32, 64, ...)         |
| `-A` / `--all`          | Show hex, dec, oct, bin, bytes, ascii, width simultaneously        |
| `-E` / `--escape`       | `\xNN` escape sequence output                                      |
| `--c-array`             | C byte-array literal output                                        |
| `-D` / `--decode`       | Decode integer bytes to ASCII string (alias: `--ascii-decode`)     |
| `-n` / `--encode`       | Encode ASCII string to hex integer (alias: `--ascii-encode`)       |
| `-t` / `--signed`       | Interpret result as signed two's complement                        |
| `-v` / `--verbose`      | Print parse/eval diagnostics to stderr                             |
| `-u` / `--upper`        | Uppercase hex digits                                               |
| `-P` / `--no-prefix`    | Omit `0x` / `0o` / `0b` prefix                                    |
| `-h` / `--help`         | Show help                                                          |

---

## Running Tests

```bash
python3 -m pytest tests/ -v
# 124 tests, 0 failures
```

---

## C Port Roadmap

The architecture is designed so a C port only touches `cli/`:

1. Translate `core/engine.py` → `core/engine.c` + `core/engine.h`
   - Each function has a `C equivalent:` comment with its C signature
   - Use GMP (`mpz_t`) or `__int128` for big integers
   - `evaluate()` becomes a recursive-descent parser (replaces `eval()`)
2. Translate `cli/bitmath.py` → `cli/bitmath.c` using `getopt_long()`
3. `FormatSpec` maps directly to a C struct — field names and types are identical
