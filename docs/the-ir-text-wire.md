# The IR text wire: what it derives, and whether we need it

The driver emits the whole IR as text and parses it straight back, in memory,
before handing anything to the emitter. `CodexWasmHarness.codex` argues that
this is load-bearing rather than an optimisation waiting to be removed. It
costs **949.6 MB of 3,042 MB** — 31% — which `docs/memory.md` measures.

This is what it actually derives, and what happened when it was removed.

## The prose was stale; the mechanism is field slots

The harness says the wire "DERIVES what the AST does not carry —
`IRTextEmitter.codex:404-406` computes a record's implicit type parameters from
its field types as it serialises." **Neither half of that is in the code.**
`ir-emit-tparams-text` quotes the list it is given, and `parse-rec-def` parses
the list it is given; no type parameter is computed on either side.

What the wire really derives is a **positional field slot**. `ir-emit-expr`
resolves every `IrFieldAccess` and `IrFieldStore` against the receiver's record
type and writes the answer into the field name:

```
is IrFieldAccess (r) (f) (ty) (sp) ->
  let fi = ir-resolve-field-index (ir-expr-type r) f
  in "(field-access " & ir-emit-expr r & " " & ir-quote (ir-field-with-index f fi) & ...
```

`parse-bag` goes out as `parse-bag/14`. The IRChapter carries only the name.

## Why it looked load-bearing

Without a slot, `wat-field-slot` fell through to `find-field-in-typedefs`,
which searches every type-def **by name** and takes the first match. That is
right only when a field name is unique to one record, and in the compiler it is
very much not:

| | |
|---|---|
| record types in the subject | 235 |
| distinct field names | 565 |
| **names appearing at more than one slot index** | **59** |
| `span` alone | slots 1, 2, 3, 4, 8, 16 across 21 records |

Emitting the compiler through the name-only path produces **4,968,460
different bytes out of 6,760,737** — 73% of the module, silently.

## Three implementations of one function

The same resolution exists three times, and only the wasm plug was reading
somebody else's answer:

| | how it gets a field's slot |
|---|---|
| `IRTextEmitter` | `ir-resolve-field-index` against the receiver's `RecordTy` |
| `X86_64Compound` | `find-record-field-index` against the receiver's `RecordTy` — bare metal never sees the wire |
| `plugs/zig` | **discards it.** `zig-field-name` strips the `/slot` and emits `rec.field`, and zig resolves the offset |
| `plugs/wasm` | read it out of the field name, and only computed it when absent |

The wasm plug already contained the type-directed resolver — `wat-slot-in-ty`,
against `ir-expr-type rec` — as the *fallback*. The change is to ask the type
first and keep the wire's number as the fallback.

## What the measurement says

Three binaries, same input, byte comparison of the emitted WAT:

| | on the compiler's own 2.9 MB source | on 29 safari units, 78 KB–13.5 MB |
|---|---|---|
| **type-directed vs wire** | identical, 6,760,737 B | 29/29 identical |
| **wire removed from the driver** | identical, 6,760,737 B | 29/29 identical |
| name-only, no type *(control)* | **4,968,460 bytes differ** | — |

The control is the point: the comparison is not blind, it detects a wrong
resolver at 73% of the module. All 30 outputs are whole modules — they open
`(module`, close `)`, export `_start`, and the smallest carries 75 functions.

With the wire removed from the driver, on the compiler's own source:

```
peak RSS   3,532 MB  ->  2,588 MB     -945 MB, 27%
wall       46.3 s    ->  43.0 s
output     byte-identical
```

`docs/memory.md`'s phase probe predicted 949.6 MB from the two wire rows. It
came in at 945 MB, which is the instrument being right about something before
it was tried.

## What is settled and what is not

**Settled**: the wire's field-slot derivation is redundant for this plug, on
30 programs, and depending on it made a caller that hands over an IRChapter
directly silently wrong. The plug change is on `wasm-slot-from-type` and is
byte-identical to the current emitter everywhere it was measured.

**Not settled**: whether the wire carries anything else that some other
consumer needs. The zig plug discards slots, so nothing here changes for it —
but `CodexZigHarness` takes the same round trip and its stated reason is the
type-parameter claim above, which is not in the code and which nobody has
re-derived. Before removing the wire from a driver that is not ours, that
question needs its own answer.

**Not done here**: this project's own harness still takes the round trip. The
plug change is what makes dropping it safe; dropping it is a separate step,
worth 27% of the ceiling.
