# codex-wasm-transpiler

`codexwasm` is one program. Codex source in, WebAssembly out. **It is itself a
wasm module**, so the thing that compiles Codex to wasm is a wasm module that
node — or eventually a browser — runs.

```
node tools/runwasm.mjs generated/codexwasm.wasm prog.codex --out prog.wat
```

That is the whole artifact. This repository builds it, and checks the one
property that makes it trustworthy.

## The invariant

**The module compiles the source that produced it, and gets itself back, byte
for byte.**

```
generated/codexwasm-subject.codex   the compiler + the wasm emitter + a driver
        |  compiled by codexwasm
        v
generated/codexwasm.wat             6,754,407 bytes of WebAssembly text
        |  assembled by wabt
        v
generated/codexwasm.wasm            835,443 bytes  <-- THE ARTIFACT
        |  handed the same subject again
        v
        the same 6,754,407 bytes, or it is a finding
```

Every chapter of the Codex compiler and the whole of `codex/plugs/wasm` run to
produce that answer. `./build.py` ends by checking it and exits non-zero if it
breaks.

It is not a proof of correctness. It says the artifact is self-consistent:
running as wasm, it agrees with what produced it. What it rules out is drift —
a change that alters the emitted bytes cannot hide, because the artifact is
the comparand.

**The obvious way to fake it** would be a "compiler" that emitted a program
which prints its input back. This one isn't, and `./build.py` checks rather
than asks you to believe: every build puts `samples/arith.codex` through the
artifact, assembles it, runs it, and compares nine lines against
`samples/arith.expected`. It prints 42, 92, 610 and 5050, none of which appear
in that program's source, and 92 is the eight-queens count reached by
backtracking.

## The roads

The first generation has to come from somewhere, and there is more than one
somewhere. What makes these ROADS rather than a bootstrap ladder is that the
invariant does not care which one was taken — so when two of them run, their
answers must be identical, which is a stronger statement than either makes
alone.

| road | how generation 1 is produced | needs | status |
|---|---|---|---|
| `self` | `generated/codexwasm.wasm` compiles the subject | node | **works** |
| `zig` | `$CODEXZIG` builds a native `codexwasm`, which does | node + zig | **works** |
| `guest` | the seed compiles the subject to IR, and the wasm plug emits from it — both on bare metal | QEMU | not built — `docs/the-guest-road.md` |

**`self` is the destination.** Nothing but node, no zig anywhere, the artifact
carrying itself forward — which is what makes this repository's product a
thing you can use without the rest of the toolchain existing.

**`zig` is how the first generation was reached**, and it is kept because it
answers a question `self` cannot: whether the module agrees with a *different
machine* running the same emitter. `./build.py --road both` requires them to
emit identical bytes, and they do.

**`guest` is the road that would make the genesis zig-free as well.** Today
`generated/codexwasm.wasm` traces back through `codexzig`, so the zig plug is
in this artifact's trusted base even though no zig runs to use it. Only the
guest road removes that, and whether it fits is a memory question — see below,
and `docs/the-guest-road.md` for the argument and what has to be measured.

## Memory is the first priority

**wasm32 has a hard 4 GiB ceiling.** Not a policy, an address space — and the
emitted prelude bump-allocates and never reclaims, so a run's whole working set
has to fit at once. The compiler-sized subject sits close to that wall:

| | |
|---|---|
| peak linear memory, compiling the subject | **3,694.7 MB** |
| the wasm32 ceiling | 4,096 MB |
| headroom | **9.8%** |

That is the number this project is organised around. Two gates, because one
number cannot answer two questions:

- **the ceiling gate** asks *will this die* — refuse above `CXWASM_MAX_PCT`
  (default 95%). Raising it moves the gate, not the ceiling.
- **the ratchet** asks *did we get worse* — refuse more than
  `CXWASM_DRIFT_PCT` (default 2%) over `generated/MEMORY.bank`, a number taken
  deliberately with `--rebank` and never a stage output some earlier run
  overwrote on its way past.

The measurement is exact rather than sampled: because nothing is ever
reclaimed, final linear memory **is** peak linear memory, and
`tools/runwasm.mjs` reads it off the module and prints `CXWASM-MEM`.

The first version of this build had one gate at 90% and it fired on its first
run, at 90.2%. That is the distinction above, paid for within an hour of being
written.

## Requirements

| | | why |
|---|---|---|
| `$COBBLESTONE_ROOT` | a pinned [Cobblestone](https://github.com/damiant3/Cobblestone) worktree | every chapter is read from here; nothing is vendored |
| `node` | 22.x | runs the module, and assembles the WAT |
| `wabt` | via `npm ci` in `tools/` | the assembler — and the emitter's only type checker |
| `pwsh` | at `~/.local/pwsh/pwsh` | the checkout's own bundler is PowerShell |
| a quiet box | ~4 GB free RAM | see Memory; nothing here takes a lock |
| `$CODEXZIG` + `zig` 0.16.0 | only for `--road zig` | not needed to use the artifact |

**This repository is coupled to Cobblestone and always will be.** The
discipline is not to pretend otherwise: point `$COBBLESTONE_ROOT` at a
worktree that is DETACHED at a named revision, so nothing moves under a build,
and let `generated/PROVENANCE` record which one every artifact came from.
`PROVENANCE.md` has the pins and the reasoning. The variable is deliberately
not `$CODEX_ROOT`, which belongs to the ladder and whose HEAD moves all day.

```
git -C <cobblestone> worktree add --detach ~/showell_repos/cobblestone-wasmpin <rev>
export COBBLESTONE_ROOT=~/showell_repos/cobblestone-wasmpin
cd tools && npm ci && cd ..
./build.py                      # self road: check the artifact against itself
./build.py --road zig           # re-derive it from source, through codexzig
./build.py --road both          # both, and require them to agree
./build.py --prove-gate         # show the comparison can actually FAIL
```

## Just want a compiler?

You do not need any of the above. `generated/codexwasm.wasm` is in this
repository and it is the whole program:

```
node tools/runwasm.mjs generated/codexwasm.wasm prog.codex --out prog.wat
node tools/wat2wasm.mjs prog.wat prog.wasm
```

No QEMU, no PowerShell, no zig, no checkout. `generated/codexwasm.wat` is the
same thing in text, tracked so it can be read and diffed without running
anything.

## What is here

```
build.py         the driver: six stages, two gates, no guests
cobblestone.py   where the sister checkout is, and which one it is
source/          the parts that are ours: the chapter list, the driver chapter,
                 and a stub the chapter list needs
tools/           runwasm.mjs (the runner and the memory instrument),
                 wat2wasm.mjs, and the wabt pin
samples/         arith.codex and its expected output -- compiled, assembled and
                 run on every build, so the artifact is checked doing real work
generated/       everything the build emits, tracked, including the artifact
docs/            the roads not taken, and what the fixed point does not cover
FINDINGS.md      what building this found in codex/plugs/wasm
PROVENANCE.md    the pins, along every axis that can change a byte
```

Deliberately absent: any Codex source from Cobblestone (read from
`$COBBLESTONE_ROOT`), and any call into a sibling repository's scripts. **This
repository is self-sufficient and pays for it in drift** —
`source/bundle_codexwasm.ps1` is a copy of codex-zig-transpiler's chapter list
with exactly one line different, so `diff` is the drift check. That trade is
deliberate: a chapter list that goes stale breaks loudly at the next build,
where a shared one would make this project's subject move for reasons two
repositories away.

## Sister repos

- **[Cobblestone](https://github.com/damiant3/Cobblestone)** — Damian's
  self-hosted language, compiler and OS. The compiler and the wasm plug both
  come from here. This repository is downstream of it and vendors none of it.
- **[codex-zig-transpiler](https://github.com/showell/codex-zig-transpiler)** —
  the same idea for the zig plug, and the direct ancestor of this one:
  `codexzig` is what builds the native binary on the `zig` road, and its
  chapter list is what `source/bundle_codexwasm.ps1` is a copy of.
- **safari-codex** — a port of a driving screensaver to Codex, verified four
  ways. Its fourth arm is where `codex/plugs/wasm` was first made to run at
  all, and `CodexWasmHarness.codex` was written there. Every wasm-plug defect
  this project inherits is written up in its `WASM_FINDINGS.md`.
- **codex-zig-ladder** — the verification ladder: it compiles the compiler two
  ways and requires the answers to agree. That is a *comparison* machine. This
  repository holds one *invariant*, and is deliberately much smaller.
