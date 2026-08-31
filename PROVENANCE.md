# PROVENANCE: what this artifact is made of

**A build that cannot say what it measured is not evidence, and the fixed
point cannot supply the difference — it holds just as well against the wrong
source.** So every axis that can change a byte of `generated/codexwasm.wat` is
named here, and `generated/PROVENANCE` records what each one was on the build
that produced the tracked artifacts.

This file is the standing policy. That file is the receipt.

## The axes

| axis | what it is | how it is pinned |
|---|---|---|
| the chapters | the Codex compiler and `codex/plugs/wasm/WasmEmitter.codex` | `$COBBLESTONE_ROOT`, a **detached** worktree; the revision is stamped |
| the chapter LIST | which chapters make the subject | `source/bundle_codexwasm.ps1`, ours, in this repository |
| the bundling RULES | how cites and quires resolve | the checkout's own `plug-build-lib.ps1` — deliberately not copied |
| the driver | what the program does with them | `source/CodexWasmHarness.codex`, ours |
| the road | which machine produced generation 1 | `--road`, stamped |
| `codexzig` | on the `zig` road only, and only for generation 1 | `$CODEXZIG`, sha256 stamped |
| `wabt` | assembles the WAT; changes the `.wasm`, never the `.wat` | `tools/package-lock.json` |

`build.py` refuses to guess any of them. `$COBBLESTONE_ROOT` unset is an
error, not a search; `$CODEXZIG` set-but-empty is an error, because that is
what a failed candidate build leaves behind and falling back to some other
transpiler would report on a binary nobody named.

## The pins, as of 2026-08-31

```
COBBLESTONE_ROOT  ~/showell_repos/cobblestone-wasmread  branch wasm-plug-buffered-read
                  at cac5851b, which is 15ef1862 plus this project's own plug fixes
CODEXZIG          ~/showell_repos/codexzig-safari/generated/local/codexzig
                  built in that worktree at 432b80a, from 15ef1862
```

`~/showell_repos/cobblestone-wasmpin`, detached at `15ef1862`, is the pin this
project started from and is kept as the last revision that is somebody else's
work alone.

**The current pin is a BRANCH and the build says so on every run**, which is
the arrangement rather than an oversight: `wasm-plug-buffered-read` is ours and
under active development, so detaching would mean re-attaching to edit. What
the NOTE buys is that nobody reads a `generated/PROVENANCE` from this period
believing the revision could not have moved. Detach it when the branch stops
moving.

**Detached is the requirement, not a preference.** A worktree with a branch
checked out moves when somebody works on that branch — and `15ef1862` is the
tip of `safari`, which safari-codex develops on. `build.py` prints a NOTE and
carries it into `generated/PROVENANCE` when the checkout it was given is on a
branch, because a build whose source moved underneath it looks exactly like a
build whose source did not.

**One worktree per consumer, and never the shared checkout.** The box already
holds `cobblestone-safari` (safari-codex's, on a branch it advances),
`cobblestone-pin` (codex-zig-transpiler's), and now `cobblestone-wasmpin`
(ours). Three worktrees of one repository is not duplication; it is what stops
one project's `git checkout` from silently re-pointing the other two.

## The uncomfortable part: this cannot be reproduced from upstream

`15ef1862` is Update 53 — upstream `58b08c38` — plus **fourteen unlanded
commits**, eleven of them in the plugs. Seven of those are the wasm-plug
defect fixes without which **no Codex program that computes with `Real`
assembles at all**, and the emission ceiling fix without which a subject this
size dies at 4 GiB mid-emit. They are sent as
[Cobblestone PR 111](https://github.com/damiant3/Cobblestone/pull/111) and
were open when this was written.

```
cac5851b  wasm plug: the emitted runtime made 2.9 million host calls and 56,000 grows   <- OURS
15ef1862  plugs: the mask split's failure mode was impossible, and the ceiling is a gate now
2a53929f  wasm plug: a guard needs its OWN scrutinee local, and a mention is not a call
e6f09556  wasm plug: neither env import is reachable, and the comment said one was fixed
2660d3af  zig plug: size the prelude mask split to the table, not to a written-down 50
ab4612aa  wasm plug: a branch's GUARD is part of the branch, in both walkers
1893cf1e  zig plug: emit a chapter one definition at a time, with the prelude's answer
3c13334d  zig plug: join a list literal's elements once, as emit-zig-defs already says to
2aff6e4d  wasm plug: emit a list literal in halves, and the 4 GiB ceiling goes away
121b61fb  wasm plug: ask the IR which imports a module needs, not the emitted text
b5b1bb74  wasm plug: a ^ b was emitting a * b, and INT64_MIN printed as garbage
e8486215  wasm plug: Real is an f64, not an i64 with f64 bits in it
2f7e7375  zig plug: emit real-to-bits and bits-to-real, the f64 bitcasts
13edc9a6  zig plug: run.ps1 creates its output directory and falls back to the seed
37d7eed7  zig plug: emit real-to-int and real-from-int, the f64 conversions
```

`WasmEmitter.codex` at `15ef1862` is **byte-identical** to PR 111's tip — the
PR was cherry-picked from Update 53 rather than cut from the integration
branch, so the shas differ and the content does not. Every quadratic-to-linear
fix the safari work found is therefore in this tree, the list-literal halving
included. `cac5851b` is one commit of our own on top, not yet sent.

**There is no version of this project that waits for them to land.** Building
on unlanded work is not a shortcut taken here; it is the situation, and the
only honest response is to say so at every axis rather than to let a green
build imply a checkout anybody else has. When PR 111 lands, the pin moves to a
revision that names it and this section says so instead.

The four wasm-plug defects still OPEN upstream are in safari-codex's
`WASM_FINDINGS.md`, and what THIS project found is in `FINDINGS.md`.

## What the artifact's provenance runs through

`generated/codexwasm.wasm` was first produced on the `zig` road, so its
ancestry runs through `codexzig` — which is itself the Codex compiler emitted
by `codex/plugs/zig` and bootstrapped under QEMU by the seed. **No zig runs to
USE the artifact**, and the `self` road rebuilds it with none in sight, but a
first generation traced back through the zig plug is still a first generation
traced back through the zig plug.

Only the `guest` road removes that, and `docs/the-guest-road.md` is where
whether it fits is argued. Until then this is a fact about the artifact and
belongs here rather than in a footnote.
