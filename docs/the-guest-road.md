# The guest road: a genesis with no zig in it

**Today's artifact traces back through `codexzig`.** No zig runs to use it, and
`--road self` rebuilds it with none in sight, but the first generation was
emitted by a native binary that the zig plug produced. The zig plug is in this
artifact's trusted base, and saying "no zig in the toolchain" while that is
true would be a claim about the daily loop dressed up as a claim about the
artifact.

The guest road is what removes it. This file is the design and the arithmetic;
it is not built.

## The shape

Two guests, which is exactly what safari-codex's fourth arm already does per
module — this is that, pointed at a subject three times larger:

```
1  bundle the wasm plug as a ring plug          host    source/WasmPlugRing.codex
2  compile it on the seed        -> .cdx        GUEST   ~18 s for safari's
3  compile the subject on the seed -> IR text   GUEST   the front end, on bare metal
4  run the ring plug over that IR -> WAT        GUEST   the emitter, on bare metal
```

Nothing in that chain has ever seen zig. Stage 4's WAT is then assembled and
must equal `generated/codexwasm.wat` — so the road does not merely replace the
genesis, it becomes a **diverse double-compiling witness**: the same emitter,
on the seed's x86 and as a wasm module, emitting the same bytes for the same
IR. That is a materially stronger statement than the `zig` road's, which
compares wasm against a binary the zig plug built.

The pieces exist. safari-codex has `harness/WasmPlugRing.codex`,
`harness/bundle_wasmplug.ps1` and `harness/wasm_plug_build.py`; the ladder has
`ring_compile` and `codex_vm`, which take the box's compute lock. Whether they
are borrowed or copied is the drift decision this repository has already made
once — copied, and `PROVENANCE.md` says why.

## Whether it fits is arithmetic, and the arithmetic is nearly known

The guest cannot simply be made bigger. codex-zig-transpiler measured this and
the numbers are not ours to re-argue: **3072 MB boots, 3584 MB and 3968 MB die
before READY**, because the boot stub sets its stack from a four-byte RAM-size
cell and triple-faults on a value it cannot use. `guest.py` refuses 4096 MB
outright. So the cap is 3072 MB and there is no lever.

What the equivalent stages cost for the *zig* transpiler, whose subject is the
same size as ours to within a few hundred bytes:

| stage | what it does | peak |
|---|---|---|
| compile the subject | 2.9 MB source in, 9.9 MB of IR out | **2454 MB** |
| transpile it | 9.9 MB of IR in, 2.3 MB of zig out | 916 MB |

**Stage 3 is shared** — same front end, same subject size, one chapter
different — so it should land near 2454 MB with about 618 MB of margin. That
stage is the risk that is already understood.

**Stage 4 is the open question and it cuts both ways.** The wasm emitter puts
out 6.75 MB of WAT where the zig emitter puts out 2.3 MB of zig, which argues
up. But it *streams*: `emit-wasm-chapter-stream` brackets each definition in
`__heap-save`/`__heap-restore`, so its cost is the maximum over definitions
rather than the sum, where `emit-zig-chapter` was whole-text when that 916 MB
was measured. That argues down, and possibly by a lot.

**Nobody has measured it, and it is cheap to.** safari-codex's
`harness/mem_probe.py` reads the frontier between phases exactly — the bump
heap never reclaims, so `__heap-save` IS the running total and the difference
between two marks is what a phase cost, with no sampling. Pointing it at this
subject through the native binary gives the emit-only number, and the emit-only
number is what decides whether stage 4 fits under 3072 MB.

**That measurement is the next thing to do on this road**, and it costs no
guest at all.

## What it does not solve

The 4 GiB ceiling. The guest road changes where the FIRST generation comes
from; it does nothing about the module needing 3,694.7 MB to compile the
subject, which is a property of the emitted program and not of who emitted it.
Those are two different problems and only one of them is this file's.
