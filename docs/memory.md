# Memory: where the 3.6 GB goes

**This is the project's first priority**, so this file is measurements and not
plans. `README.md` has the gates; this is what they are watching.

## The three ceilings

They are different ceilings with different failure modes, which is why there
are three gates and not one.

| ceiling | what it is | where we are | how it fails |
|---|---|---|---|
| **4 GiB linear memory** | wasm32's address space | 3,694.7 MB — **90.2%** | trap, then worse: `bump_alloc`'s own arithmetic is i32 and wraps at exactly 4 GiB (FINDINGS 4) |
| **4 MiB input** | `$read_file_uni`'s fixed buffer | 2,904,749 B — **69.3%** | **silently**, compiling a prefix of the program (FINDINGS 1) |
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

## What is still unmeasured, and the instrument for it

**The split inside that 2,731 MB floor.** How much is the front end and how
much is the zig emitter is exactly what would say whether there is anything
worth attacking on this side of the fence.

The instrument exists and costs no guest. The bump heap never reclaims, so
`__heap-save` **is** the running total of everything allocated so far, and the
difference between two phase boundaries is what that phase cost — exactly,
with no sampling. safari-codex's `harness/mem_probe.py` writes those marks into
a harness mechanically rather than by hand, for the reason that a
hand-instrumented pair of harnesses can differ somewhere else and nobody would
see it.

Doing that here means a harness variant, which means a different subject and a
different artifact — a build variant, not the tracked one. That is the next
piece of work on this file.

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
