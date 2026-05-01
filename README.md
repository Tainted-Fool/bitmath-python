# bitmath

An exploit-dev friendly bitwise calculator for the command line.

```
bitmath "0xc6 ^ 0x79"                    →  0xbf
bitmath -a "0xdeadbeef"                  →  all representations at once
bitmath -b -s "0xc6 ^ 0x79"             →  1011 1111
bitmath -W 1 -s -e little "0xdeadbeef"  →  ef be ad de
bitmath -E "0xdeadbeef"                  →  \xde\xad\xbe\xef
bitmath --c-array "0xdeadbeef"           →  { 0xde, 0xad, 0xbe, 0xef }
echo "0xff & 0x0f" | bitmath             →  0xf     (stdin)
```

---

## Installation

```bash
git clone <repo>
cd bitmath
chmod +x bitmath
# optional: put it on your PATH
cp bitmath /usr/local/bin/bitmath
```

**Requirements:** Python 3.8+. No third-party packages.

---

## Project Structure

```
bitmath/
├── bitmath              # executable entry point (chmod +x this)
├── core/
│   ├── __init__.py      # public API exports
│   └── engine.py        # ALL business logic — zero I/O, zero CLI
├── cli/
│   └── bitmath.py       # argument parsing + I/O only, calls core.process()
└── tests/
    └── test_engine.py   # 87 tests covering every function in core/
```

The `core/` and `cli/` split is intentional. Every function in `core/engine.py`
has a documented C equivalent in comments — when a C port happens, only `cli/`
changes and the core logic is a direct translation target.

---

## Usage

```
bitmath [flags] "expression"
```

Quote expressions to protect `|`, `~`, `<`, `>` from the shell.
If no expression is given, bitmath reads from **stdin**.

---

## Operators

| Operator    | Meaning       | Example                       | Result   |
|-------------|---------------|-------------------------------|----------|
| `&`         | AND           | `bitmath "0xff & 0x0f"`       | `0xf`    |
| `\|`        | OR            | `bitmath "0xf0 \| 0x0f"`     | `0xff`   |
| `^`         | XOR           | `bitmath "0xaa ^ 0x55"`       | `0xff`   |
| `~`         | NOT (bitwise) | `bitmath "~0x00 & 0xff"`      | `0xff`   |
| `<<`        | Shift left    | `bitmath "0x01 << 4"`         | `0x10`   |
| `>>`        | Shift right   | `bitmath "0x80 >> 3"`         | `0x10`   |
| `+` `-` `*` | Arithmetic    | `bitmath "0x10 + 0x20"`       | `0x30`   |

Parentheses work: `bitmath "(0x41 ^ 0x20) << 1"`.

> **`~` (NOT) note:** Python's `~` produces a negative number on arbitrary-precision
> integers. Mask to your intended width: `~0x00 & 0xff` → `0xff`.

---

## Literal Formats

Mix any of these in a single expression:

| Format     | Syntax       | Example        |
|------------|--------------|----------------|
| Hex        | `0x` prefix  | `0xdeadbeef`   |
| Decimal    | plain int    | `255`          |
| Octal      | trailing `o` | `377o`         |
| Binary     | trailing `b` | `11111111b`    |

```bash
bitmath "0xff & 11110000b"    →  0xf0
bitmath "377o ^ 0x0f"         →  0o360
bitmath "1010b | 0101b"       →  1111
```

---

## Output Format Auto-Inference

Output format mirrors the **first literal** in your expression:

| Input type    | Default output  |
|---------------|-----------------|
| `0x...`       | hex (`0xbf`)    |
| plain integer | decimal (`191`) |
| `...o`        | octal (`0o6`)   |
| `...b`        | binary (`1111`) |

```bash
bitmath "0xc6 ^ 121"    →  0xbf   (hex wins, appears first)
bitmath "198 ^ 0x79"    →  191    (decimal wins, appears first)
```

---

## Output Override Flags

| Flag | Output              | Example                       | Result        |
|------|---------------------|-------------------------------|---------------|
| `-x` | hex                 | `bitmath -x "198 \| 121"`    | `0xff`        |
| `-d` | decimal             | `bitmath -d "0xdeadbeef"`     | `3735928559`  |
| `-o` | octal               | `bitmath -o "255"`            | `0o377`       |
| `-b` | binary              | `bitmath -b "0xc6 ^ 0x79"`   | `10111111`    |

Binary output has **no leading zeros** and **no spaces** by default. Use `-s` to
add nibble-grouped spaces.

---

## Grouped Hex Output

Two flags control how the hex output is visually chunked.
Neither adds spaces unless you also pass `-s`.

### `-W [N]` — byte groups

Groups output in chunks of **N bytes** (= N×2 hex chars). Default N = 2.

```bash
bitmath -W 1 "0xdeadbeef"         →  deadbeef      # compact, paste-ready
bitmath -W 1 -s "0xdeadbeef"      →  de ad be ef   # 1 byte per group
bitmath -W 2 -s "0xdeadbeef"      →  dead beef     # 2 bytes per group
bitmath -W 4 -s "0xdeadbeef"      →  deadbeef      # full value as one group
```

### `-w [N]` — nibble groups

Groups output in chunks of **N nibbles** (= N hex chars). Default N = 2.

```bash
bitmath -w 1 -s "0xdeadbeef"      →  d e a d b e e f   # 1 nibble per group
bitmath -w 2 -s "0xdeadbeef"      →  de ad be ef        # 2 nibbles (= 1 byte)
bitmath -w 4 -s "0xdeadbeef"      →  dead beef          # 4 nibbles (= 2 bytes)
```

`-W 1` and `-w 2` produce identical output — 1 byte = 2 nibbles.

---

## Spacing Flag

```
-s / --spaces    add spaces between groups  (works with -b, -W, -w)
```

Without `-s`, groups concatenate with no separator — paste-ready for payloads.
With `-s`, groups are space-separated for readability.

```bash
bitmath -W 2 "0xdeadbeef"         →  deadbeef       # compact
bitmath -W 2 -s "0xdeadbeef"      →  dead beef       # readable

bitmath -b "0xbf"                  →  10111111        # compact
bitmath -b -s "0xbf"               →  1011 1111       # nibble-grouped
```

---

## Endianness

```
-e big      big-endian display (default)
-e little   reverse byte order before display
```

`-e little` alone implies `-W` with the default group size.

```bash
bitmath -e little "0xdeadbeef"             →  efbeadde
bitmath -e little -s "0xdeadbeef"          →  efbe adde      # default group=2
bitmath -W 1 -s -e little "0xdeadbeef"    →  ef be ad de    # explicit 1-byte groups
```

Endianness operates at the **byte** level — bytes are reversed first, then grouped.

---

## Display Options

| Flag             | Effect                                         | Example output     |
|------------------|------------------------------------------------|--------------------|
| `-u` / `--upper` | Uppercase hex digits                           | `0XDEADBEEF`       |
| `-P` / `--no-prefix` | Omit `0x` / `0o` / `0b` prefix            | `deadbeef`         |
| `--width BITS`   | Force display width (8/16/32/64/128/256)       | see below          |

```bash
bitmath -x -u "0xdeadbeef"         →  0XDEADBEEF
bitmath -x -P "0xdeadbeef"         →  deadbeef
bitmath -W 1 -s --width 64 "0xff"  →  00 00 00 00 00 00 00 ff
```

---

## Special Output Modes

### `-a` / `--all` — show everything at once

```bash
bitmath -a "0xdeadbeef"
  hex    0xdeadbeef
  dec    3735928559
  oct    0o33653337357
  bin    1101 1110 1010 1101 1011 1110 1110 1111
  bytes  de ad be ef
  width  32-bit
```

### `-E` / `--escape` — `\x` escape sequence

```bash
bitmath -E "0xdeadbeef"                    →  \xde\xad\xbe\xef
bitmath -E -e little "0xdeadbeef"          →  \xef\xbe\xad\xde
bitmath -E -u "0xdeadbeef"                 →  \xDE\xAD\xBE\xEF
```

### `--c-array` — C byte-array literal

```bash
bitmath --c-array "0xdeadbeef"             →  { 0xde, 0xad, 0xbe, 0xef }
bitmath --c-array -e little "0xdeadbeef"   →  { 0xef, 0xbe, 0xad, 0xde }
bitmath --c-array -u "0xdeadbeef"          →  { 0XDE, 0XAD, 0XBE, 0XEF }
```

---

## Stdin Support

If no expression argument is given, bitmath reads from stdin:

```bash
echo "0xc6 ^ 0x79" | bitmath                  →  0xbf
echo "0xdeadbeef"   | bitmath -W 1 -s          →  de ad be ef
printf "0xff & 0x0f\n" | bitmath -b            →  1111
```

---

## Width Inference

The display width (8/16/32/64/...) is inferred from the widest literal in your
expression, rounded up to the nearest power-of-2 byte boundary. Override with
`--width`.

```bash
bitmath -W 1 -s "0xff"                   →  ff              # 8-bit
bitmath -W 1 -s "0xffff"                 →  ff ff           # 16-bit
bitmath -W 1 -s "0xdeadbeef"             →  de ad be ef     # 32-bit
bitmath -W 1 -s "0xdeadbeefcafebabe"     →  de ad be ef ca fe ba be  # 64-bit
bitmath -W 1 -s --width 32 "0xff"        →  00 00 00 ff     # forced 32-bit
```

---

## Real-World Examples

**XOR key recovery**
```bash
bitmath "0xc6 ^ 0x79"              →  0xbf
```

**All representations at a glance**
```bash
bitmath -a "0xdeadbeef"
```

**Shellcode byte sequence**
```bash
bitmath -W 1 -s "0xdeadbeef"       →  de ad be ef
```

**`\x` escape for Python/C payloads**
```bash
bitmath -E "0xdeadbeef"            →  \xde\xad\xbe\xef
```

**C array for a shellcode buffer**
```bash
bitmath --c-array "0xdeadbeef"     →  { 0xde, 0xad, 0xbe, 0xef }
```

**Little-endian address for a ROP chain**
```bash
bitmath -W 1 -s -e little "0x08048460"   →  60 84 04 08
```

**Port number to little-endian wire bytes**
```bash
bitmath -W 1 -s -e little "4444"         →  5c 11
```

**Bitmask check**
```bash
bitmath -b -s "0b11001100 & 0b10101010"  →  1000 1000
```

**Flag extraction (bits 4–7)**
```bash
bitmath -b -s "0xAB & 0xF0"             →  1010 0000
```

**Rotate right 4 bits (32-bit)**
```bash
bitmath -b -s "((0xdeadbeef >> 4) | (0xdeadbeef << 28)) & 0xffffffff"
→  1111 1101 1110 1010 1101 1011 1110 1110
```

**Force 64-bit width display**
```bash
bitmath -W 1 -s --width 64 "0xdeadbeef"
→  00 00 00 00 de ad be ef
```

---

## Flag Reference

| Flag                 | Meaning                                                  |
|----------------------|----------------------------------------------------------|
| `-x`                 | Force hex output                                         |
| `-d`                 | Force decimal output                                     |
| `-o`                 | Force octal output                                       |
| `-b`                 | Force binary output (no leading zeros)                   |
| `-W [N]`             | Byte-grouped hex, N bytes per group (default 2)          |
| `-w [N]`             | Nibble-grouped hex, N nibbles per group (default 2)      |
| `-s` / `--spaces`    | Add spaces between groups                                |
| `-e big\|little`     | Byte order (default: big; little implies -W if unset)    |
| `--width BITS`       | Force display width: 8, 16, 32, 64, 128, 256             |
| `-a` / `--all`       | Show hex, dec, oct, bin, bytes simultaneously            |
| `-E` / `--escape`    | `\xNN` escape sequence output                            |
| `--c-array`          | C byte-array literal output                              |
| `-u` / `--upper`     | Uppercase hex digits                                     |
| `-P` / `--no-prefix` | Omit `0x` / `0o` / `0b` prefix                          |
| `-h` / `--help`      | Show help                                                |

---

## Running Tests

```bash
python3 -m pytest tests/ -v
```

87 tests covering every core function, formatter, and the full `process()` pipeline.

---

## C Port Roadmap

The architecture is designed so a C port only touches `cli/`:

1. Translate `core/engine.py` → `core/engine.c` + `core/engine.h`
   - Each Python function has a `C equivalent` comment noting its C signature
   - Use GMP (`mpz_t`) or `__int128` for arbitrary-precision arithmetic
   - `evaluate()` becomes a recursive-descent parser (no `eval()`)
2. Translate `cli/bitmath.py` → `cli/bitmath.c` using `getopt_long()`
3. `tests/` gains a parallel `tests/test_engine_c.sh` using the compiled binary

The `FormatSpec` struct maps directly: each Python field becomes a C struct member
with the same name and an equivalent type.
