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
| 1 | a source over 4 MiB was truncated, and the error blamed the wrong thing | **misleading diagnostic** (not silent, as first written) | **fixed** |
| 2 | `print-text` and `write-binary` both land on fd 1 | divergence from the zig plug | open, worked around here |
| 3 | `read-file-uni` costs one host call per byte | ergonomics | **fixed** — and it was not the slowness |
| 4 | the bump allocator's ceiling arithmetic is i32 and wraps | ceiling behaviour, read but not executed | open |
| 5 | `memory.grow` is called ~56,000 times to reach 3.7 GB | **ergonomics — 12x on node, and browsers pay it** | **fixed** |
| 6 | the runtime prelude is emitted whole, never shaken | surface | open, and small |
| 7 | a declared export is deleted unless the driver ROOTS it | **it hits the browser case hardest** | **fixed** in this driver |
| 8 | `when` over a `Boolean` emitted `(i64.const True)` | **the construct never worked on this target** | **fixed** |
| 9 | ~45 emitted runtime helpers are unprefixed, and collide with user definitions | **a name a program may not use, with no warning** | open |
| 10 | a builtin with no arm emits a dangling funcref instead of a diagnostic | **looks like a complete module** | **fixed** |
| 11 | a guard's scrutinee bump leaked into its sibling branches | wrong module, from ordinary code | **fixed** |

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

## 1. A source over 4 MiB was truncated, and the error named the wrong cause — FIXED

`wat-rt-read-file` allocates a fixed 4,194,304-byte buffer and then reads the
wire to its end, storing only while there is room:

```
(local.set $cap (i32.const 4194304))
...
(if (i32.lt_s (local.get $n) (local.get $cap)) (then  ... store ... )))
```

**The loop keeps consuming and keeps discarding**, so the compiler is handed a
PREFIX of the program.

**This entry originally called that a silent wrong answer. Measured, it is
not, and the difference matters.** A prefix that no longer defines what it
references fails the halt gate, so what a user actually gets is:

```
CODEGEN-HALTED: 2 error(s); no wasm emitted; first CDX3002 Undefined name: final-answer
```

about a file that plainly defines `final-answer`. Loud, and pointing at the
wrong thing — nothing anywhere mentions the input, and the one fact that would
explain the error is the one fact not reported. It is genuinely silent only
when the prefix is self-consistent, and then the dropped tail was unreachable
and the module is right anyway.

That is a smaller defect than first written and still worth fixing, because
this project's own subject is 2.92 MB and grows every time a paragraph is
added to the driver.

**Fixed**: both readers now extend by re-bumping, `read-file-raw`'s own idiom
from two functions below. The second one, `$read_serial_cce`, is the one that
mattered most and not for source — it is how `WasmPlug.codex` receives IR
TEXT, which runs several times the size of its program. Measured after: the
same 4,605,510-byte unit reads to the end and emits a 78,196-byte module,
**byte-identical to the uncapped native compile of the same unit**, which
runs and prints what it should.

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

## 7. A declared export is deleted unless the driver roots it — FIXED

`wasm-exports` lets a chapter say what it exports (safari-codex
`WASM_FINDINGS` 5, fixed on `wasm-slot-from-type`). Declaring one does not
make it survive, and there are two ways to lose it before the emitter looks.

**Pruning** is the expected one: `ir-prune-unreachable-roots` drops a
definition nothing calls, `wasm-exports` included, so a driver that prunes has
to root both.

**The worst case is the normal case.** A function written to be called from
JavaScript typically has *no* callers inside the chapter at all, which is
exactly what dead-code elimination removes. So the first thing a newcomer
does — write a function, declare it exported, call it from a page — was the
thing most likely to produce a module without it.

**The fix is that a declared export is a root**, which is what a root already
means: this is live because something outside calls it. `CodexWasmHarness`
reads `wasm-exports` out of the IR *before* pruning and adds those names, plus
`wasm-exports` itself, to the roots it hands `ir-prune-unreachable-roots`.
Twelve lines of driver, no compiler change, no plug change.

**It fixes more than predicted, and the wrong prediction is the useful part.**
Reading `keep-single-caller` — which keeps a candidate only when its call
count is exactly 1 — I wrote that a one-caller export is folded into its
caller and lost before any root can help, and that only the zero-caller case
was fixable. Measured, that is wrong: **inlining substitutes and pruning
deletes.** The pass copies the body to the call site, leaving the definition
unreferenced, and it is the *pruner* that removes it — which is precisely what
a root prevents.

| in-chapter call sites | before rooting | after |
|---|---|---|
| 0 | deleted | **exported** |
| 1 | deleted | **exported** |
| 2+ | exported | exported |

End to end, from JavaScript, on a module built this way:

```
  exports available: __heap_reset, disk_reserve, _start, greet, twice
  greet(21) = 42
  twice(5) = 20
  twice(100) = 400
```

`twice` is the one whose body was inlined into `opening` — `$opening` calls
`$greet` directly now — and it survives only because it is rooted, and it
still computes. Two passes had been read as one mechanism because they have
the same effect on the common case.

**What is still the driver's problem** is that every driver has to do this.
`opening.codex` has its own hardcoded roots list, so the two-guest arm would
need the same change there. That is the argument for the export declaration
being an input to the pipeline the way the entry point is, rather than
something each driver remembers.

## 8. `when` over a `Boolean` emitted `(i64.const True)` — FIXED

`IrLitPat` carries the literal's TEXT, so a `when` on a Boolean gives
`(lit-pat "True" boolean)` and the emitter spliced that straight into
`(i64.const True)`. `wat2wasm` refuses it: *unexpected token "True", expected
a numeric literal*. **`when` over a Boolean had never worked on this target.**

The zig plug has had `zig-lit-pat-text` for exactly this since it was written;
the wasm plug had no equivalent. Found by assembling the ladder's 580-program
corpus, where three programs are this.

A `Text` literal pattern is the same shape and is **not** fixed: it needs a
string-table entry and a text comparison rather than `i64.eq`. One corpus
program, `literal-subpattern`.

## 9. The emitted runtime shares a flat namespace with user definitions

Four corpus programs define a function whose sanitised name is already an
emitted runtime helper — `text-compare`, `text-eq` — and the module is refused
for redefinition. Those two names are not unlucky: **about 45 of the runtime's
helpers carry no prefix at all** — `list_at`, `char_at`, `substring`,
`bump_alloc`, `fn_arity`, `read_byte`, `bool_to_text` and the rest. Roughly
half the runtime already uses `cx_` and the other half does not.

Every unprefixed name is a name a program may not use, and nothing says so.
The failure is at least loud — wasm forbids duplicate names, so it is a
refusal rather than a silent substitution — but it is loud in the assembler,
about a function the user did write.

The fix is mechanical: one prefix, every helper, every call site. It is worth
doing carefully rather than quickly, because it moves every byte of every
module, and the fixed point is the only thing that would notice a slip.

## 10. A builtin with no arm emitted a dangling funcref, not a diagnostic — FIXED

161 of the corpus's 169 assembly refusals are this, across 48 distinct
builtins. A builtin the plug has no arm for is not emitted as a bad call —
the name is treated as a value, reaches the funcref path, and comes out as
`call_indirect` against a local nothing declared.

**Most of the 48 are device access and should not have a wasm form** —
`port-out-32` (35 programs), `read-mmio-32` (17), `gpu-mem-write`,
`net-send-raw`, `process-spawn`, `uefi-read-key-ex`. A module cannot do port
I/O and no arm will change that.

**So the defect is the failure mode rather than the absence.** An unsupported
builtin should be refused at emission with a diagnostic naming it, the way the
halt gate refuses a program with errors. Instead the plug produces a module
that looks complete and the user learns from `wat2wasm`, in a message about an
undefined local variable that names the builtin only because the builtin
happens to be the variable.

Some of the 48 are not device builtins at all and are simply holes:
`vec-splat` and `vec-load-at` (safari's open finding 7), `text-to-unicode-bytes`,
`unicode-bytes-to-text`, `real-approx-to-bits`, `sort-ascending`, `ask`,
`write-file`, `fail`.

`docs/the-corpus-sweep.md` is the whole census.

**Fixed by making the fall-through refuse.** A name that is not bound in the
function, is not a constructor and has no arity is not a local — there is
nothing for it to be — and both the bare-name path and the apply path emitted
`(local.get $name)` anyway. They now emit
`(unreachable) (; no wasm form for port-out-32 ;)`.

`unreachable` rather than an assembly error, because it is stack-polymorphic:
**the module assembles**, every path that does not reach the builtin runs, and
a path that does reach it traps rather than doing something plausible. The
comment is `(; ;)` and not `;;` deliberately — a line comment would eat the
rest of the line, and this emitter writes very long ones.

The plug already had this idea: `wat-no-such-thing` refuses four hardware
builtins exactly this way, and its prose says *"there is no approximation of a
disk sector or an I/O port that is better than refusing."* It had four names on
it. The corpus found 48.

| the corpus, before | after |
|---|---|
| assembled 411 of 580 | **assembled 566 of 580** |
| refused **169** | refused **14** |

417 modules are byte-identical across the change and no program that assembled
before refuses now, so nothing that worked was disturbed.

## 11. A guard's scrutinee bump leaked into its sibling branches — FIXED

Visible only once finding 10's noise was cleared. `lang-smoke` and
`plug-oracle-arith` declare `(local $_s)` and then read `$_ss` and `$_sss`.

`emit-wat-guard-test` gave a guard its own scrutinee by writing

```
emit-wat-expr (__record-set ctx "scrut-depth" (ctx.scrut-depth + 1)) guard
```

**`__record-set` mutates in place and returns the same record.** So once one
branch's guard had been emitted, the shared `ctx` carried the bumped depth into
every sibling branch and into the enclosing match. A second guarded branch read
its tag and its constructor binders from `$_ss`, a third from `$_sss`, while the
scrutinee had been stored in `$_s` and nothing declared the others.

The minimal case is two guarded constructor branches:

```
when s is C (r) when r > 10 -> ... is R (n) when n > 5 -> ... is otherwise -> ...
```

Fixed by building a fresh `WasmCtx` for the guard. The guard still gets its own
depth — which is what safari's finding 10 asked for, and that property is tested
here and holds: a `when` inside a guard gets `$_ss`, the branches below still
read `$_s`, and the answers come out right.

**Finding 10's fix introduced this one**, by reaching for `__record-set` to
express "the same context but one deeper". And the compiler *has* a diagnostic
for the hazard — CDX6020, thirteen of them in this very build — but it inspects
`__record-set` only inside a record construction's **field**, not passed as an
argument to a call whose caller keeps using the original. That blind spot is a
compiler-side lead.

**How it was found is worth as much as the fix.** It was invisible until
finding 10's noise was cleared; then the corpus named two programs; then a
hand-written test found a *different* shape the corpus does not contain; and
the bisect that located it went through three variants that were all fine.
Two of my own steps along the way were wrong — the first hypothesis blamed the
ctor binders, and one bisect round measured a stale binary and reported a
mismatch that had already been fixed.
