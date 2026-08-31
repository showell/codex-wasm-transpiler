# FINDINGS: what building this found in `codex/plugs/wasm`

**The plug is the subject here, not the compiler.** These are things the wasm
emitter does that were found by making it compile itself — a program four
times larger than anything that had been put through it, reading its input
from the wire and writing an artifact rather than a verdict.

They are separate from safari-codex's `WASM_FINDINGS.md`, which is where the
plug was first made to run at all and where four defects are still open (`show`
of a `Real`, the export allowlist, the vector ops, the unreachable `env`
imports). This project inherits all four and restates none of them.

Line numbers are against the pin in `PROVENANCE.md`.

| # | finding | kind | status |
|---|---|---|---|
| 1 | a source over 4 MiB is silently truncated | **silent wrong answer** | open, gated here |
| 2 | `print-text` and `write-binary` both land on fd 1 | divergence from the zig plug | open, worked around here |
| 3 | `read-file-uni` costs one host call per byte | ergonomics | **fixed** — and it was not the slowness |
| 4 | the bump allocator's ceiling arithmetic is i32 and wraps | ceiling behaviour, read but not executed | open |
| 5 | `memory.grow` is called ~56,000 times to reach 3.7 GB | **ergonomics — 12x on node, and browsers pay it** | **fixed** |
| 6 | the runtime prelude is emitted whole, never shaken | surface | open, and small |
| 7 | a declared export can be INLINED AWAY, silently | **surprise, and it hits the browser case hardest** | open, now visible |

3 and 5 are fixed on `wasm-plug-buffered-read`, and **guarded there rather
than here**: `codex/plugs/wasm/check-emitted-runtime.ps1` asserts the emitted
runtime's invariants on any `.wat`, `wasm-e2e.ps1` calls it per subject, and
`build.py` calls the checkout's copy rather than keeping one of its own. The
guard lives with the plug because that is where a regression would happen and
who would have to see it — a reviewer needs nothing from this repository.

It is shown to fire: four violations against a module emitted before the
fixes, and one each against the floor lowered to a page, the clamp deleted, a
second `memory.grow` inlined, and the reader back to a byte per call.

---

## 1. A source over 4 MiB is silently truncated

`wat-rt-read-file` allocates a fixed 4,194,304-byte buffer and then reads the
wire to its end, storing only while there is room:

```
(local.set $cap (i32.const 4194304))
...
(if (i32.lt_s (local.get $n) (local.get $cap)) (then  ... store ... )))
```

**The loop keeps consuming and keeps discarding.** There is no diagnostic, no
truncation marker and no non-zero exit; the compiler is handed a PREFIX of the
program and compiles it. What comes out is a module for a program nobody
wrote — which, for a prefix that happens to parse, is the worst available
outcome.

`read-file-raw`, two functions below, has the fix already: it grows by bumping
again rather than truncating, because consecutive `$bump_alloc` calls with
nothing allocated between them are contiguous, so the reservation simply
extends. Its own comment says the fixed cap "silently DROPS what does not fit,
which for an artifact is a truncation wearing the colour of a complete
answer". That was written about this function and this function still does it.

**This project runs at 69.4% of that cap.** `build.py` refuses above
`CXWASM_INPUT_PCT`, because a gate that fires is worth more than a finding
that is filed — but the gate is ours and protects only this repository.

Mechanism read from the source; the truncating branch has not been executed
here, because everything this project compiles is under the cap.

## 2. `print-text` and `write-binary` both land on fd 1

The zig plug puts `print-text` on **stderr** — it becomes `std.debug.print` —
and `write-binary` on stdout. That is why `codexzig < prog.codex 2> prog.zig`
works: the program comes out one side and the diagnostics the other, and the
native `codexwasm` on the `zig` road inherits the same split.

The wasm plug sends both to fd 1. So the same harness, compiled by the two
plugs, produces a separated pair of streams on one and a single interleaved
stream on the other — and a program whose job is to emit an artifact and
report on it cannot separate them on wasm at all.

`tools/runwasm.mjs` splits by line: the module's first line is exactly
`(module`, and no diagnostic line can be. That works and it is a workaround.
The fix is a convention — one of the two streams belongs on fd 2 — and it is
not this project's to pick, because safari-codex's fourth arm compares what
these modules print and would move with it.

## 3. `read-file-uni` cost one host call per byte — FIXED, and it was not the slowness

`$read_byte` issued one `fd_read` with a one-byte iovec and `$read_file_uni`
called it in a loop, so reading the 2.9 MB subject was **2.9 million host
calls**. It now reads 64 KB into a buffer and hands out one byte, which leaves
every caller's boundary decisions untouched byte for byte. The old comment
argued that a line ends at a newline and reading ahead would swallow what
follows "with nowhere to put them back"; the buffer **is** somewhere to put
them back, which dissolves the argument rather than trading against it.

`$read_file_raw` reads fd 0 for itself, so it now drains what `$read_byte` has
buffered and not handed out before reading any more. Without that, a program
calling `read-line-uni` and then `read-file-raw` would silently lose up to
64 KB — a regression this fix would otherwise have introduced.

**The correction is the useful part of this entry.** This finding originally
said the gap between the two runtimes *was* this — 210 s under node against
19 s under wasmtime, "the call boundary, not the compile". That was a
mechanism named from plausibility rather than measured, and it is wrong.
Fixing it took 223 s to 210 s. The real cause is finding 5, and it was found
by asking what scaled: node was only 2.2x slower than wasmtime on a 696 KB
input and 11.7x on a 2.9 MB one, and something that grows with size is not a
per-byte constant.

Both changes are worth having and only one of them mattered.

## 4. The bump allocator's ceiling arithmetic is i32 and wraps

`wat-rt-bump-alloc` writes the honest thing for a refused grow —
`(if (i32.eq (memory.grow ...) (i32.const -1)) (then (unreachable)))` — but the
two quantities compared first are computed in i32 and both wrap at exactly the
address space:

```
(local.set $need (i32.add (local.get $ptr) (local.get $size)))
(local.set $have (i32.mul (memory.size) (i32.const 65536)))
```

At 65,536 pages — a full 4 GiB — `65536 * 65536` is 2^32 and `$have` is **0**.
For a pointer near the top, `$ptr + $size` wraps to a small number and
`$need > $have` is false, so the allocator returns a pointer and sets
`$heap_ptr` to the wrapped value without growing anything.

So the last stretch before the ceiling is not the clean trap the code was
written to give.

**This project runs at 90.7% of that ceiling**, which is why it is written down
rather than filed as theoretical. It is read from the source and has **not**
been demonstrated by execution.

## 5. `memory.grow` was called ~56,000 times — FIXED, and this was the slowness

`$bump_alloc` grew by exactly the pages an allocation needed. That is the
obvious reading and it is one `memory.grow` per 64 KB of heap — about 56,000
of them to reach the 3.7 GB the compiler wants for its own source.

It is free on some hosts and ruinous on others, and the two this plug runs
under sit on opposite sides. Measured on a module that does nothing but grow
and touch the last word of each new page:

| | node 22 | wasmtime 27 |
|---|---|---|
| 56,000 grows of 1 page → 3.5 GB | **166.83 s** | **0.21 s** |
| 16,000 grows of 1 page → 1.0 GB | 5.45 s | |
| 1,000 grows of 16 pages → 1.0 GB | **0.38 s** | |

**The middle two rows are the finding**: same final size, same bytes touched,
fourteen times the wall clock for growing in smaller pieces. V8's cost per
grow rises with the memory it already holds, so the COUNT has to come down.
wasmtime reserves the address space once and grow is bookkeeping.

**A browser pays this and wasmtime does not**, and the browser is where this
plug is going. 167 s of a 223 s compile was `memory.grow`.

Fixed by growing in **16 MB steps** — a FIXED step and not a geometric one,
because doubling overshoots by up to 12.5% and at 3.7 GB of a hard 4 GiB
ceiling that is not headroom anybody has. 16 MB wastes at most 16 MB and
reaches the ceiling 0.4% sooner. `$grow_by` gives the policy one home; there
were two copies of the growth arithmetic, and a policy in two places is a
policy that gets changed in one.

Measured end to end, the compiler compiling its own source under node:
**223.1 s to 18.1 s**, with the fixed point holding on the new emitter.

## 6. The runtime prelude is emitted whole

`wat-runtime-funcs` concatenates every `wat-rt-*` unconditionally. Only two
things vary: the `env` imports, which are asked for by the IR, and the closure
trampolines, which are keyed on the maximum arity in the program.

Measured — the same one-line program and `arith`, through this artifact:

| | WAT | assembled | runtime funcs |
|---|---|---|---|
| one `print-line-uni` | 76,842 | 12,113 | 72 |
| `arith` | 88,158 | 13,404 | 72 + 14 |
| `codexwasm` | 6,760,737 | 836,901 | 72 + rest |

**All 72 appear in both**, so nothing is dropped for the program that uses
almost none of them. The zig plug does shake — nine list helpers are in
`arith.zig` and absent from a one-line program's — but there the shaking is
cosmetic, because `zig build-exe` dead-strips anyway. Here the prelude
**ships**.

**It is 12 KB, and that is the whole of it.** 90% of a hello-world module and
1.4% of `codexwasm`. Recorded because the difference between the two plugs is
real and somebody will otherwise measure it again; not worth an afternoon.

## 7. A declared export can be inlined away

`wasm-exports` lets a chapter say what it exports (safari-codex
`WASM_FINDINGS` 5, fixed on `wasm-slot-from-type`). Declaring one does not
make it survive, and there are two ways to lose it before the emitter looks.

**Pruning** is the expected one: `ir-prune-unreachable-roots` drops a
definition nothing calls, `wasm-exports` included, so a driver that prunes has
to root both.

**Inlining is the one that will surprise people**, because the definition is
reachable and still disappears. Measured while building the feature: a chapter
declaring `["greet", "twice"]` where `twice` has exactly one caller exports
only `greet` — the single-caller inline pass folded `twice` into its caller
and deleted it. Give `twice` a second caller and both export.

**The worst case is the normal case.** A function written to be called from
JavaScript typically has *no* callers inside the chapter at all, which is
precisely the shape both passes remove. So the first thing a newcomer does —
write a function, declare it exported, call it from a page — is the thing most
likely to produce a module without it.

Neither is fixed. Both are the driver's to fix, and both are now *visible*: a
declared name that matches no surviving definition emits a comment into the
module naming it. Without that, "you spelled it wrong" and "the optimiser ate
it" are both discovered in a browser console with no way to tell them apart.

The real fix is for the export declaration to be a root — the pipeline should
be told that these names are live because something outside the program calls
them, which is exactly what a root means. That is a driver change plus an
argument about where the list belongs, and it is worth making before anybody
is invited to write Codex for the web.
