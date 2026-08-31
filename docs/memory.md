# Memory: where the 3.6 GB goes

**This is the project's first priority**, so this file is measurements and not
plans. `README.md` has the gates; this is what they are watching.

## The three ceilings

They are different ceilings with different failure modes, which is why there
are three gates and not one.

| ceiling | what it is | where we are | how it fails |
|---|---|---|---|
| **4 GiB linear memory** | wasm32's address space | 2,772.2 MB — **67.7%** | trap, then worse: `bump_alloc`'s own arithmetic is i32 and wraps at exactly 4 GiB (FINDINGS 4) |
| **4 MiB input** | `$read_file_uni`'s fixed buffer | 2,908,990 B — **69.4%** | **silently**, compiling a prefix of the program (FINDINGS 1) |
| **3072 MB guest** | the seed's boot stub, if the guest road is ever built | unmeasured | the guest parks in `hlt` with nothing on the wire |

## Is it the emitter or the front end? Mostly the front end.

The obvious reading is that the wasm emitter is expensive — it puts out
6,754,407 bytes of WAT where the zig emitter puts out 2,476,457 bytes of zig,
nearly three times the text. That is true and it is not where the bill is.

**Same subject file, both native binaries, back to back on an idle box.** The
front end does byte-for-byte identical work in both columns — same input, same
phases, same IR, same wire round trip — and the only difference is which
emitter runs at the end:

| | peak RSS | emitted | wall |
|---|---|---|---|
| `codexzig` on `codexwasm-subject.codex` | **2,731 MB** | 2,476,457 B of zig | 64 s |
| `codexwasm` on `codexwasm-subject.codex` | **3,523 MB** | 6,754,407 B of WAT | 46 s |
| the wasm emitter's cost above the zig one | **+792 MB** | +4.3 MB | −18 s |

Two things follow, and the second one is the important one.

**The wasm emitter is not the outlier it looks like.** It emits 2.7x the text
for 1.29x the peak and does it in less wall time, which is what
`emit-wasm-chapter-stream`'s per-definition `__heap-save`/`__heap-restore`
bracket buys — its cost is the maximum over definitions where a whole-text
emitter's is the sum.

**Even if the wasm emitter were free, we would be at 67% of the ceiling.**
2,731 MB is a floor made of the front end plus whatever the zig emitter itself
costs, and it is reached before the wasm emitter emits one byte more than the
zig one would. So the headroom problem is majority-owned by the shared front
end — the Codex compiler — and not by `codex/plugs/wasm`.

That reframes the work. Shaving the emitter buys the 792 MB at most, or about
19 points of ceiling; the other 67 points are upstream, in a program this
repository reads and does not own.

**The mapping from native RSS to wasm linear memory is close to 1:1**:
3,523 MB native against 3,694.7 MB of linear memory for the same work, the
wasm side about 5% higher. So the native binary is a fair, fast proxy for the
number that actually matters, which makes iterating on this cheap.

## Where it actually goes, phase by phase

`./probe_memory.py` writes `__heap-save` marks into a copy of the driver, builds
that, and runs it on the real subject. The bump heap never reclaims, so the
frontier at a mark **is** the running total and the difference between two marks
is exactly what that phase allocated — no sampling, no profiler.

| phase | this phase, MB | % |
|---|---|---|
| tokenize | 53.0 | 1.7% |
| scan | 33.8 | 1.1% |
| parse (`doc`) | 107.3 | 3.5% |
| scope (`ch`) | 8.8 | 0.3% |
| **resolve names (`rr`)** | **315.4** | **10.4%** |
| **type check (`cr`)** | **698.7** | **23.0%** |
| lower + IR pipeline + lift | 37.9 | 1.3% |
| **emit IR text** | **344.6** | **11.3%** |
| **parse IR text back** | **605.0** | **19.9%** |
| everything else in the front end | 8.6 | 0.3% |
| **emit (a FLOOR, not a peak)** | **828.2** | **27.2%** |
| | **3,042.5** | |

Two independent instruments agree on the split: the probe has 2,214 MB retained
when emission starts, plus the 512 MB deck reservation, against the runner's
2,852 MB at the first `fd_write` — within the ~5% the native and wasm arms
differ by.

### The IR text wire is the biggest single thing, and it is ours — REMOVED

**`emit IR text` plus `parse IR text back` is 949.6 MB — 31% of everything.**
The driver emits the whole IR as text and parses it straight back, in memory,
and `CodexWasmHarness.codex` argues at length that this is load-bearing rather
than an optimisation waiting to be removed: the wire DERIVES what the AST does
not carry, because `IRTextEmitter.codex` computes a record's implicit type
parameters from its field types as it serialises. The direct hand-off worked on
85 programs and then emitted a monomorphic record whose fields still said `a`.

So the round trip is not wrong. What the measurement says is what it COSTS, and
a third of the budget is a lot to pay for a derivation that happens as a side
effect of serialising. The fix that would keep the property and drop the cost is
to do that derivation on the `IRChapter` directly — which is a compiler change
and a good one on its own terms, since a derivation that only happens during
serialisation is invisible to every consumer that does not serialise.

**It was removed on 2026-08-31 and the fixed point held**: 3,716.1 MB to
2,772.2 MB, 90.7% of the ceiling to 67.7%, byte-identical output on 30
programs. The derivation turned out to be a field slot rather than a type
parameter, and the plug can do it itself from the receiver's type — which bare
metal already does and the zig plug discards. `docs/the-ir-text-wire.md` is
the whole account. The table above is the state BEFORE that change; the two
wire rows are now zero and every other row is unmoved.

### Type checking is the biggest phase that is nobody's design decision

**698.7 MB, 23%**, with name resolution behind it at 315.4 MB. Together they are
a third of the budget and they are plain compiler work on a 2.9 MB program.
This is the part that is genuinely upstream and genuinely just large.

### Emission retains 828 MB despite streaming

`emit-wasm-chapter-stream` brackets every definition in
`__heap-save`/`__heap-restore`, so a definition's working set is released before
the next one starts — and yet the frontier is 828 MB higher after emission than
before it. That is what is allocated OUTSIDE the brackets: the string table, the
data sections, the runtime text, the type definitions and the two import scans
are all built before streaming begins and held for its duration.

**That number has not been broken down and it is the next thing to measure**,
because unlike the two rows above it, it is in a file this project can change.

## What is still unmeasured, and the instrument for it

**The 828 MB emission retains outside its per-definition brackets.** The phase
probe stops at the boundary of `emit-wasm-chapter-stream`; breaking that row
down means marks inside the emitter, which is an emitter change rather than a
driver change. It is the largest number left that this project can act on
alone.

**A dropped phase is invisible**, which is why `probe_memory.py` refuses when
the driver has a binding its pass did not account for: the table would simply
be shorter and the missing cost would fold into the row above. That guard was
earned twice — safari's copy found its own `else let` blind spot after a year,
and the first run of ours put `deck-adv` in the prologue skip-list, which made
the first row the baseline and reported tokenize as 0.0 MB.

## Why the ratchet exists

The first version of this build had a single gate at 90% of the ceiling and it
fired on its own first run, at 90.2%. The temptation is to raise it, and
raising it is exactly wrong: an absolute gate set above today's peak permits
every creep below it, and set at today's peak it fires on noise.

So the ceiling gate answers *will this die* at 95%, and the ratchet answers
*did we get worse* against `generated/MEMORY.bank` — a number taken
deliberately with `--rebank`. A bank is a decision. A stage output that some
earlier run overwrote on its way past is not a baseline, however much it looks
like one.

## Growing the memory is not free, and it is not a memory cost

The allocator used to call `memory.grow` once per 64 KB of heap — 56,000 times
to reach 3.7 GB. wasmtime does not notice; V8's cost per grow rises with the
memory it already holds, so **167 s of a 223 s compile was `memory.grow`**.
Growing in 16 MB steps took the fixed-point check from 223 s to 18 s under
node. `FINDINGS.md` item 5 has the microbenchmark.

It is filed here because it is memory-shaped and it is not a memory PROBLEM:
it cost time, not bytes. What it cost in bytes is the other direction and small
— a fixed 16 MB step wastes at most 16 MB, and with the 64 KB read buffer
beside it the peak moved 3,694.7 → 3,716.1 MB, or 0.58%, well inside the
ratchet. That is the trade and it was taken deliberately.

**The lesson generalises past this plug.** A number that is fine on the host
you develop against and ruinous on the host you ship to will not show up in any
gate that measures the artifact — only in one that measures the artifact ON
THAT HOST. This project runs the fixed point under node for that reason, and
the browser leg will want its own.
