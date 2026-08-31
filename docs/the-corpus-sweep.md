# The corpus sweep: 580 programs through the wasm plug

Until this, everything in this repository was checked against **thirty**
programs — the compiler's own source, twenty-nine safari units, and two
samples. That is a thin basis for a compiler, and it is a basis chosen by
what we happened to be working on.

The ladder's corpus holds 580 programs as **IR text**, which is exactly what
`codex/plugs/wasm/WasmPlug.codex` consumes. So the whole set can be put
through the emitter without compiling anything: build a driver that reads IR
from stdin, emit, and hand every module to `wat2wasm`.

**`wat2wasm` is the point.** It is this emitter's type checker, and it is the
only thing that sees a certain class of defect: a builtin the plug has no arm
for does not come out as a bad call — the name is treated as a value, reaches
the funcref path, and emits `call_indirect` against a local nothing declared.
A grep cannot find that. The assembler names it and the line.

## The result

| | |
|---|---|
| programs | **580** |
| emitted a module | **580** (56 s for the set) |
| assembled | **411** |
| **refused by the assembler** | **169 — 29%** |

Nothing failed to *emit*. Every refusal is a module the plug produced happily
and the assembler would not take.

## The four classes

| | count | |
|---|---|---|
| a builtin with no arm, emitted as a dangling funcref | **161** | 48 distinct names |
| a program definition colliding with an emitted runtime helper | **4** | `text-compare`, `text-eq` |
| a `Text` literal pattern compared with `i64.eq` | 1 | `literal-subpattern` |
| a non-ASCII identifier reaching `wat-sanitize` | 1 | `ident-letters` |
| a type-class no-instance marker reaching the emitter | 2 | |

Plus **3 fixed while writing this**: a `when` over a `Boolean` emitted
`(i64.const True)`, because `IrLitPat` carries the literal's text and the
emitter spliced it in. The zig plug has had `zig-lit-pat-text` for this since
it was written. `when` over a Boolean had never worked on this target.

## The 48 builtins with no arm

| `port-out-32` | 35 |
| `read-mmio-32` | 17 |
| `vec-splat` | 10 |
| `net-send-raw` | 9 |
| `process-spawn` | 9 |
| `gpu-mem-write` | 7 |
| `uefi-read-key-ex` | 6 |
| `process-get-cap` | 5 |
| `peek-16` | 5 |
| `atomic-load` | 4 |
| `ask` | 3 |
| `write-file` | 3 |
| `net-recv-raw` | 3 |
| `process-get-network-scope` | 3 |
| `text-to-unicode-bytes` | 2 |
| `net-status` | 2 |
| `real-approx-to-bits` | 2 |
| `poke-mmio-32` | 2 |
| `--list-len` | 2 |
| `sort-ascending` | 2 |
| `fail` | 2 |
| `vec-load-at` | 2 |
| `memory-fence` | 1 |
| `process-restrict-cap` | 1 |
| `block-select` | 1 |
| `unicode-bytes-to-text` | 1 |
| `key-load` | 1 |
| `gpu-out` | 1 |
| `gpu-mem-read` | 1 |
| `is-whitespace` | 1 |
| `read-text` | 1 |
| `store-get` | 1 |
| `get-a` | 1 |
| `get-value` | 1 |
| `port-in-16` | 1 |
| `abs` | 1 |
| `-ss` | 1 |
| `process-wait` | 1 |
| `-sss` | 1 |
| `poke-mmio` | 1 |
| `tick` | 1 |
| `suggested-vector-width` | 1 |
| `tag-equal` | 1 |
| `uefi-read-key` | 1 |
| `port-out-16` | 1 |
| `vec-extract` | 1 |
| `vec4-splat` | 1 |
| `max` | 1 |

**Most of these are device access and arguably should not have a wasm form**
— `port-out-32`, `read-mmio-32`, `poke-mmio-32`, `uefi-read-key-ex`,
`gpu-mem-write`, `net-send-raw`, `process-spawn`, `block-select`. A wasm
module cannot do port I/O and no arm will change that.

**The defect is the failure mode, not the absence.** An unsupported builtin
should be refused with a diagnostic naming it, at emission, the way the halt
gate refuses a program with errors. Instead the plug emits a module that
looks complete, and the user finds out from `wat2wasm` — if they run it — in
a message about an undefined local variable, which names the builtin only by
coincidence of it being the variable.

**And some are not device builtins at all**: `vec-splat` and `vec-load-at`
(10 and 2 — this is safari's open finding 7), `text-to-unicode-bytes`,
`unicode-bytes-to-text`, `real-approx-to-bits`, `sort-ascending`, `--list-len`,
`ask`, `write-file`, `fail`. Those are holes rather than refusals.

## The namespace collision is the one that surprised me

Four programs define a function whose sanitised name is already an emitted
runtime helper — `text-compare` and `text-eq` — and the module is refused for
redefinition. That is not those two names being unlucky. **About 45 of the
emitted runtime's helpers have no prefix at all**: `list_at`, `char_at`,
`substring`, `bump_alloc`, `fn_arity`, `read_byte`, `bool_to_text`, and the
rest. Roughly half the runtime already uses `cx_`; the other half does not,
and every unprefixed name is a name a program may not use.

The fix is mechanical — one prefix, every helper, every call site — and it is
worth doing carefully rather than quickly, because it moves every byte of
every module and the fixed point is the only thing that would notice a slip.

## What this sweep does not do

It compiles and assembles. It does **not run** the 411 modules or compare
what they print against the zig plug's answer for the same program, which is
where a *wrong answer* would show up rather than a refused module. The corpus
carries a `.zig` beside every `.ir`, so that arm is available and is the
obvious next thing.
