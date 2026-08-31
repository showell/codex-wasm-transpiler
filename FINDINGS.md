# FINDINGS: what building this found in `codex/plugs/wasm`

**The plug is the subject here, not the compiler.** These are things the wasm
emitter does that were found by making it compile itself — a program three
times larger than anything that had been put through it, reading its input
from the wire and writing an artifact rather than a verdict.

They are separate from safari-codex's `WASM_FINDINGS.md`, which is where the
plug was first made to run at all and where four defects are still open (`show`
of a `Real`, the export allowlist, the vector ops, the unreachable `env`
imports). This project inherits all four and restates none of them.

Line numbers are against `cobblestone-wasmpin` at `15ef1862` — see
`PROVENANCE.md`.

| # | finding | kind | status |
|---|---|---|---|
| 1 | a source over 4 MiB is silently truncated | **silent wrong answer** | open, gated here |
| 2 | `print-text` and `write-binary` both land on fd 1 | surface / divergence from the zig plug | open, worked around here |
| 3 | `read-file-uni` costs one host call per byte | ergonomics — 10x on node | open |
| 4 | the bump allocator's ceiling arithmetic is i32 and wraps | **ceiling behaviour**, read but not executed | open |

---

## 1. A source over 4 MiB is silently truncated

`wat-rt-read-file` (`WasmEmitter.codex:2893-2914`) allocates a fixed
4,194,304-byte buffer and then reads the wire to its end, storing only while
there is room:

```
(local.set $cap (i32.const 4194304))
...
(if (i32.lt_s (local.get $n) (local.get $cap)) (then  ... store ... )))
```

**The loop keeps consuming and keeps discarding.** There is no diagnostic, no
truncation marker and no non-zero exit; the compiler is simply handed a PREFIX
of the program and compiles it. What comes out is a module for a program
nobody wrote — which, for a prefix that happens to parse, is the worst
available outcome.

The same function ends the read at a NUL or at byte 4 (EOT), so a source
carrying either is truncated there for the same reason and with the same
silence. That part is deliberate — it is the serial wire's framing, inherited
from `__bare_metal_read_serial` — but the 4 MiB cap is not framing, it is a
buffer.

**This project runs at 69.3% of that cap** (`codexwasm-subject.codex` is
2,904,749 bytes) and every chapter added to the subject moves it. `build.py`
refuses above `CXWASM_INPUT_PCT` of the cap, because a gate that fires is
worth more than a finding that is filed — but the gate is ours and protects
only this repository. Anybody else's large program is still truncated.

Mechanism read from the source. The truncating branch has not been executed
here, because everything this project compiles is under the cap.

## 2. `print-text` and `write-binary` both land on fd 1

The zig plug puts `print-text` on **stderr** — it becomes `std.debug.print` —
and `write-binary` on stdout. That is why `codexzig < prog.codex 2> prog.zig`
works at all: the program comes out one side and the diagnostics the other,
and the native `codexwasm` on the `zig` road inherits the same split.

The wasm plug sends both to fd 1 (`$wasi_print_text`, `$write_binary`,
`WasmEmitter.codex:1918` and `:2441`). So the SAME harness, compiled by the
two plugs, produces a separated pair of streams on one and a single
interleaved stream on the other — and a program whose job is to emit an
artifact and report on it cannot separate them on wasm at all.

`tools/runwasm.mjs` splits by line: the module's first line is exactly
`(module`, and no diagnostic line can be. That works and it is a workaround.
The fix is a convention — one of the two streams belongs on fd 2 — and it is
not this project's to pick, because safari-codex's fourth arm compares what
these modules print and would move with it.

## 3. `read-file-uni` costs one host call per byte

`$read_byte` (`:2722-2729`) issues one `fd_read` with a one-byte iovec, and
`$read_file_uni` calls it in a loop. Reading the 2,904,749-byte subject is
**2.9 million host calls**.

Measured, same module, same input, identical output:

| runtime | reading and compiling the subject |
|---|---|
| `wasmtime` 27.0.0 | 19 s |
| `node` 22 + `tools/runwasm.mjs` | 210 s |

The gap is the call boundary, not the compile: wasmtime's is a function call
and node's crosses into JS. Nothing is wrong with the answer — the two agree
byte for byte — but **node is the runtime this project targets** and the
browser is the one after it, so a 10x tax on input is paid by exactly the beds
that matter. A chunked read (fill a buffer, hand out bytes from it) is
invisible to every caller, because the framing decisions above it are already
made byte by byte.

The comment at `:2705` explains one-byte-at-a-time for `$read_line_raw`, where
it is correct: a line ends at a newline and reading ahead would swallow the
bytes after it with nowhere to put them back. `$read_file_uni` reads to the end
of the wire and has no such constraint.

## 4. The bump allocator's ceiling arithmetic is i32 and wraps

`wat-rt-bump-alloc` (`:1827-1839`) writes the honest thing for a refused
grow — `(if (i32.eq (memory.grow ...) (i32.const -1)) (then (unreachable)))` —
but the two quantities it compares first are computed in i32 and both wrap at
exactly the address space:

```
(local.set $need (i32.add (local.get $ptr) (local.get $size)))
(local.set $have (i32.mul (memory.size) (i32.const 65536)))
```

At 65,536 pages — a full 4 GiB — `65536 * 65536` is 2^32 and `$have` is
**0**. For a pointer near the top, `$ptr + $size` wraps to a small number and
`$need > $have` is false, so the allocator returns a pointer and sets
`$heap_ptr` to the wrapped value without growing anything.

So the last stretch before the ceiling is not the clean trap the code was
written to give. A second copy of the same arithmetic is at `:2205-2209`.

**This project runs at 90.2% of that ceiling**, which is why it is written
down here rather than filed as theoretical. It is read from the source and has
**not** been demonstrated by execution — no program here has been pushed over
4 GiB — and the honest reason is that doing so takes a program larger than the
one that already takes ten minutes to compile.
