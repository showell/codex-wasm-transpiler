# What the fixed point covers, and what it does not

The invariant is one comparison:

    generated/codexwasm.wasm  <  generated/codexwasm-subject.codex
        ->  bytes that must equal generated/codexwasm.wat

## What it covers

**Every chapter of the compiler and the whole wasm emitter run to produce that
answer**, on a 2.9 MB program that is the most demanding input this toolchain
has. Lexing, parsing, desugaring, scoping, name resolution, type checking and
inference, lowering, the IR pipeline, the lambda lift, the IR text wire in both
directions, and then 3,292 lines of emitter. A change anywhere in that path
that moves a byte cannot hide, because the artifact is the comparand.

**It is a self-check, not a comparison against a reference.** There is no
second implementation in the loop and no expected output written by hand. That
is a strength for drift and a weakness for correctness, and the two should not
be confused.

## What it does not cover, in four parts

**1. A defect the emitter has for its own source, it keeps.** If the emitter
compiles some construct wrongly and its own source uses that construct in a way
the wrong compilation still round-trips, both generations are wrong in the same
way and the comparison is silent. This is the general shape of every
self-hosting check and there is no cure inside the loop.

**2. It says nothing about programs the subject does not resemble.** The
subject is one large, pure, allocation-heavy program that reads a file and
writes text. It uses no `Real` arithmetic worth the name, no vectors, no `env`
imports, and it never asks for a `show` of a floating-point number — which is
exactly where safari-codex's four open findings live. A green build here is not
evidence about any of them.

**3. `samples/arith.codex` is what stops it being a quine.** The invariant
alone would be satisfied by a "compiler" that emitted a program printing its
own input back. The sample is the answer: nine lines of known output, none of
whose numbers appear in the source, through the actual artifact, on every
build. It is small, and it is doing a job no size would do better.

**4. The roads are what make it more than self-consistency.** `--road both`
requires the native binary and the wasm module — two different machines
running the same emitter — to emit identical bytes for the same subject. That
is diverse double-compiling in Wheeler's sense, and it is the only part of
this repository that could catch a fault in one machine. The `guest` road
would strengthen it further by removing zig from the comparison entirely;
`the-guest-road.md` has that argument.

## The gates around it

A comparison whose every run says `IDENTICAL` has never executed its own
mismatch branch, so the branch that gives the check its value is the one line
nobody has run.

    ./build.py --prove-gate

perturbs one byte of generation 2, requires the comparison to go RED, restores
it, and fails the build if the comparison said equal anyway. Run it whenever
the comparison changes shape.

Three more gates guard what the comparison cannot see, and each answers a
different question — `README.md` has the numbers:

- **presence**: is this a whole module at all? Baseline-free, because a
  soundness gate is blind to a no-op, and a run that dies mid-emit writes a
  truncated file that compares equal to the last run that died in the same
  place.
- **the ceiling and the ratchet**: will it die, and did it get worse.
- **the read buffer**: is the input still small enough to be read at all —
  the only one of the three ceilings that is silent.
