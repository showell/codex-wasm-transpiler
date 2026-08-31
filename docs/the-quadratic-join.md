# The quadratic join: a census of one mistake

Codex `Text` is immutable, so `a & b` allocates the whole of `a & b`. Building
a string by walking a list and concatenating as you go therefore allocates
**the sum of its own suffixes** (or prefixes, walking the other way) — work
that is quadratic in the number of pieces, for output that is linear in them.

This project has now hit that shape four separate times, each time as a
several-hundred-megabyte surprise, and each time in a file that already
contains the argument against it. This is the census, so the next one is found
by looking rather than by running out of memory.

## The four that have been found and fixed

| where | what it cost | fixed by |
|---|---|---|
| `emit-wat-list-elems` (wasm) | died at the 4 GiB ceiling on a 696 KB unit | halving, `2aff6e4d` |
| `emit-zig-list-elems` (zig) | 2,904 MB → 751 MB on the same unit | collect-and-join, `3c13334d` |
| `emit-data-sections` (wasm) | **436.8 MB**, 60% of everything emission cost | halving |
| `wat-emit-elem` (wasm) | **171.0 MB**, inside a function whose output is one line | halving |

`emit-zig-defs` in the zig plug says it in as many words — *"joining N pieces
with a right-recursive `&` copies every piece it has not reached yet, so the
cost is the output size times the number of definitions rather than the output
size. Collect and join once."* That note was written about the module and the
elements of a list literal were left doing exactly what it warns against.

## The census

A quadratic join here means a definition returning `Text` that calls itself
over an index (`i + 1`) and concatenates the result — either as the right
operand of `&` (sum of suffixes) or by threading `acc & piece` forward (sum of
prefixes). Halved spans are excluded; they are the fix, not the shape.

| | quadratic list-walks | over PROGRAM-SCALE lists |
|---|---|---|
| `codex/plugs/wasm/WasmEmitter.codex` | 28 | **7** |
| `codex/plugs/zig/ZigEmitter.codex` | 39 | **1** |
| | **67** | **8** |

**The second column is the one that matters, and it is why 67 is not an
emergency.** A walk over an expression's arguments, a record's fields or a
function's parameters is bounded by how that one construct was written — three
arguments, six fields — and quadratic in six is nothing. A walk over the
chapter's definitions, the string table, the type definitions or the arity map
grows with the whole program, and quadratic in four thousand is the difference
between a compiler that runs and one that does not.

The eight that scale with the program:

```
wasm  emit-wat-type-defs          over List ATypeDef
wasm  wat-eq-field-tests          over List ATypeDef
wasm  wat-eq-ctor-arms            over List ATypeDef
wasm  wat-eq-funcs                over List ATypeDef
wasm  wat-emit-exports-declared   over List IRDef
wasm  wat-export-misses           over List IRDef
wasm  wat-emit-exports-by-list    over List IRDef
zig   zig-call-type-args-loop     over a call's type arguments
```

Measured on the Codex compiler's own source, the type-def group is 24.9 MB and
the export group sits inside a step costing 85.2 MB. Both are real and neither
is urgent: together they are 5% of what the emitter now retains.

## Why a blanket sweep is the wrong instinct

It is tempting to fix all 67, and the temptation should be resisted in that
form, for two reasons.

**Most of them are correct as written.** Quadratic in a bounded n is not a
defect; it is the simplest code that does the job, and replacing it with a
halved span costs a reader something and buys nothing. A sweep that changes 67
call sites to fix 8 is 59 changes made for symmetry.

**The output must not move, and the argument for that is per-site.** Halving
is byte-identical *by construction* — same pieces, same order, different
association — which is exactly why it is safe on an emitter. But that argument
holds only where the pieces really are independent; a walk that threads state
through the accumulator is not the same shape and cannot be split blindly. The
eight above have to be read, not pattern-matched.

**What a sweep IS good for is finding them.** The scan that produced this
table is thirty lines and could run on every plug in the tree. The right shape
for the wider question is a detector plus a triage rule — *is this list
bounded by a construct, or by the program?* — rather than a patch.

## The wider question

The same shape is everywhere the compiler builds text: `IRTextEmitter`,
`CodexEmitter`, the X86-64 emitters, and the other forty-odd plugs nobody here
has read. This project has no standing to sweep those and no way to measure
most of them. The useful thing to send is the detector, the triage rule and the
four measurements above — the evidence that it is worth someone's afternoon,
and the means to find the sites that are.
