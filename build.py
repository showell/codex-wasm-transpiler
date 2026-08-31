#!/usr/bin/env python3
"""Build codexwasm, and check the fixed point.

    ./build.py                    build what is stale, then check
    ./build.py --road zig         re-derive the module from source, via codexzig
    ./build.py --road both        both roads; every artifact must agree
    ./build.py --force            rebuild every stage
    ./build.py --check-only       check against what is on disk
    ./build.py --prove-gate       show the fixed-point comparison can FAIL

codexwasm is one program: Codex source in, WAT out. It runs as a wasm module.

    node tools/runwasm.mjs generated/codexwasm.wasm prog.codex --out prog.wat

The whole exercise is one loop, and it closes on itself:

    subject -> WAT -> wasm -> (the same subject again) -> WAT -> diff

THE INVARIANT. The module compiles the source that produced it, and gets
itself back, byte for byte. Every chapter of the compiler and the whole wasm
emitter run to produce that answer, and there is nothing else this repository
is for.

THE ROADS. The first generation has to come from somewhere, and there is more
than one somewhere. What makes them roads rather than a bootstrap ladder is
that the invariant does not care which one was taken -- so when two of them
run, their answers must be identical, and that is a stronger statement than
either road makes alone.

    self   generated/codexwasm.wasm compiles the subject.        node only
    zig    $CODEXZIG builds a native codexwasm, which does.      node + zig
    guest  the seed compiles the subject to IR and the wasm
           plug emits from it, both on bare metal.               NOT BUILT

`self` is the destination: nothing but node, no zig anywhere, the artifact
carrying itself forward. `zig` is how the first generation was reached and is
kept because it is the only road that answers a question `self` cannot --
whether the module agrees with a DIFFERENT machine running the same emitter.
`guest` is the road that would make the genesis zig-free as well; docs/ has
the argument and the measurement that decides whether it fits.

MEMORY IS THE FIRST PRIORITY, so it is a gate and not a note. wasm32 has a
hard 4 GiB ceiling -- not a policy, an address space -- and the subject sits
near it. Every module run reports its exact peak (the emitted prelude bump
allocates and never frees, so final linear memory IS peak) and the build
refuses above CXWASM_MAX_PCT of the ceiling. A build that quietly drifts to
99% is a build that will fail on somebody else's box, on the next Update, for
reasons that will look like anything but memory.

Every artifact under generated/ is stamped with the checkout it came from,
the road it took and what it cost -- see generated/PROVENANCE. A build that
cannot say what it measured is not evidence, and the fixed point cannot
supply the difference: it holds just as well against the wrong source.
"""

import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import time

import cobblestone

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / 'source'
TOOLS = HERE / 'tools'
GEN = HERE / 'generated'
LOCAL = GEN / 'local'

PWSH = pathlib.Path.home() / '.local' / 'pwsh' / 'pwsh'
ZIG = pathlib.Path(os.environ.get('ZIG', pathlib.Path.home() / 'zig-0.16.0' / 'zig'))

SUBJECT = GEN / 'codexwasm-subject.codex'
WAT = GEN / 'codexwasm.wat'          # THE artifact, and it is readable
WASM = GEN / 'codexwasm.wasm'        # the same thing, assembled
DIAG = GEN / 'codexwasm.diag'

GEN2_WAT = LOCAL / 'codexwasm.gen2.wat'
GEN2_DIAG = LOCAL / 'codexwasm.gen2.diag'
NATIVE_ZIG = LOCAL / 'codexwasm.zig'
NATIVE_BIN = LOCAL / 'codexwasm'

SAMPLE = HERE / 'samples' / 'arith.codex'
SAMPLE_EXPECTED = HERE / 'samples' / 'arith.expected'
SAMPLE_UNIT = LOCAL / 'arith-unit.codex'
SAMPLE_WAT = GEN / 'arith.wat'
SAMPLE_WASM = LOCAL / 'arith.wasm'
SAMPLE_OUT = LOCAL / 'arith.out'

WASM32_CEILING = 4 * 1024 * 1024 * 1024
# TWO GATES, because one number cannot answer two questions.
#
#   the CEILING gate asks: will this die?  wasm32 addresses memory with i32
#   and there is no more space above 4 GiB -- not a policy, an address space.
#   The emitted bump allocator computes `ptr + size` in i32 too, so the last
#   stretch before the ceiling is not even a clean trap.
#
#   the RATCHET asks: did we get worse?  That is the question that catches a
#   change, and it is answered against generated/MEMORY.bank -- a number taken
#   DELIBERATELY with --rebank, never a stage output that some earlier run
#   overwrote on its way past. A comparand a run can rewrite is not a baseline.
#
# A single ceiling gate cannot do the ratchet's job: set it above today's peak
# and it permits every creep below it, set it at today's peak and it fires on
# noise. This build hit 90.2% on the day it was written, which is why the
# distinction was not academic for even one run.
MAX_PCT = float(os.environ.get('CXWASM_MAX_PCT', '95'))
DRIFT_PCT = float(os.environ.get('CXWASM_DRIFT_PCT', '2'))
BANK = GEN / 'MEMORY.bank'

# A THIRD CEILING, and the only silent one. `$read_file_uni` allocates a fixed
# 4 MiB buffer and then reads the wire to its end storing only while there is
# room -- so a larger source is compiled as a PREFIX of itself, with no
# diagnostic and exit 0. FINDINGS.md item 1. The gate is here because this is
# the only place that knows how big the subject got.
INPUT_CAP = 4 * 1024 * 1024
INPUT_PCT = float(os.environ.get('CXWASM_INPUT_PCT', '90'))

_t0 = time.time()
_notes = []


def say(msg=''):
    print(f'[{time.time() - _t0:6.1f}s] {msg}', flush=True)


def head(title):
    say()
    say('=' * 4 + f' {title} ' + '=' * max(4, 62 - len(title)))


def die(msg):
    say(f'FAILED: {msg}')
    raise SystemExit(1)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _fp(out):
    # Fingerprints live in local/ rather than beside the artifact: they are
    # cache control, not provenance. PROVENANCE is provenance.
    return LOCAL / (pathlib.Path(out).name + '.fp')


def fresh(out, inputs, force):
    """Is `out` already the answer for these `inputs`? Content, never mtime."""
    if force:
        return False
    fp = _fp(out)
    if not (pathlib.Path(out).exists() and fp.is_file()):
        return False
    return fp.read_text().strip() == '\n'.join(sha(i) for i in inputs)


def stamp(out, inputs):
    _fp(out).write_text('\n'.join(sha(i) for i in inputs) + '\n')


# ----------------------------------------------------------------- preflight

def preflight(road):
    head('preflight')
    LOCAL.mkdir(parents=True, exist_ok=True)

    root = cobblestone.root()
    say(f'checkout   {root}')
    say(f'           {cobblestone.revision(root)}')
    # A worktree with a branch checked out can move under a running build;
    # detached at a named rev is what this repository asks for, so a build
    # that is not on one says so rather than discovering it later.
    branch = subprocess.run(['git', '-C', str(root), 'symbolic-ref', '-q', 'HEAD'],
                            capture_output=True, text=True).stdout.strip()
    if branch:
        _notes.append(f'checkout is on {branch}, not detached -- it can move under a build')
        say(f'  NOTE: on {branch}. This repository asks for a DETACHED pin; see PROVENANCE.md')

    for tool, why in ((PWSH, 'the checkout\'s bundler is PowerShell'),
                      (pathlib.Path(shutil.which('node') or '/nonexistent'), 'the module runs under node')):
        if not tool.exists():
            die(f'missing {tool} -- {why}')
    say(f'node       {subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()}')

    if not (TOOLS / 'node_modules' / 'wabt').is_dir():
        die('no wabt -- run `npm ci` in tools/ (it assembles the WAT)')

    if road in ('zig', 'both'):
        binary = os.environ.get('CODEXZIG')
        if 'CODEXZIG' in os.environ and not binary:
            # Set but empty is a failure, not an absence: it is what a failed
            # candidate build leaves behind, and falling back to some other
            # transpiler would report on a binary nobody named.
            die('CODEXZIG is set but EMPTY -- refusing to guess which transpiler to use')
        if not binary:
            die('the zig road needs $CODEXZIG -- a codexzig binary. README has where to get one')
        if not os.access(binary, os.X_OK):
            die(f'CODEXZIG={binary} is not executable')
        say(f'codexzig   {binary}')
        say(f'           sha256 {sha(binary)[:16]}')
        if not ZIG.exists():
            die(f'no zig at {ZIG} -- set $ZIG')
        say(f'zig        {subprocess.run([str(ZIG), "version"], capture_output=True, text=True).stdout.strip()}')

    if road in ('self', 'both') and not WASM.is_file():
        die('the self road needs generated/codexwasm.wasm and there is none.\n'
            '         Take the zig road once to make it: ./build.py --road zig')
    say(f'ceiling    refuse above {MAX_PCT}% of wasm32\'s 4 GiB (CXWASM_MAX_PCT)')
    return root


# -------------------------------------------------------------------- stages

def bundle(force):
    head('1  bundle the subject')
    # NEVER CACHED, and that is the point. The bundle is a function of the
    # CHECKOUT as much as of source/, and a fingerprint over source/ alone
    # says "current" for a subject whose chapters have all changed underneath
    # it -- silently, in exactly the situation where somebody is measuring a
    # plug change and every downstream number would then be about the old one.
    # Hashing the checkout is not the fix either: a dirty worktree keeps its
    # sha. Bundling costs a second, so the honest answer is to do it every
    # time and let the SUBJECT's own sha drive every stage below.
    r = subprocess.run([str(PWSH), '-NoProfile', '-File',
                        str(SOURCE / 'bundle_codexwasm.ps1'), '-OutFile', str(SUBJECT)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not SUBJECT.is_file():
        say((r.stdout + r.stderr).strip()[-800:])
        die('the bundler refused')
    say((r.stdout or '').strip().splitlines()[-1] if r.stdout.strip() else 'bundled')
    say(f'{SUBJECT.name}: {SUBJECT.stat().st_size} bytes, sha {sha(SUBJECT)[:16]}')
    check_input_size(SUBJECT)


def check_input_size(path):
    """The read buffer's cap, which nothing else in the chain will mention.

    Checked on the way IN rather than inferred from the way out: a truncated
    source that still parses emits a perfectly good module for a program
    nobody wrote, and every gate downstream of here would call it green.
    """
    size = pathlib.Path(path).stat().st_size
    pct = 100.0 * size / INPUT_CAP
    say(f'{pathlib.Path(path).name}: {pct:.1f}% of the wasm reader\'s {INPUT_CAP}-byte buffer')
    if pct > INPUT_PCT:
        die(f'{pathlib.Path(path).name} is {size} bytes, {pct:.1f}% of the 4 MiB the\n'
            f'         emitted `$read_file_uni` can hold. Past it the source is\n'
            f'         TRUNCATED IN SILENCE and compiled as a prefix of itself.\n'
            f'         FINDINGS.md item 1. Fix the plug; do not raise the gate.')


def check_memory(stderr_text, what, ratchet=False, rebank=False):
    """Read the runner's own measurement, and gate on it both ways."""
    line = next((l for l in stderr_text.splitlines() if l.startswith('CXWASM-MEM')), None)
    if line is None:
        die(f'{what}: the runner reported no CXWASM-MEM line')
    fields = dict(kv.split('=', 1) for kv in line.split()[1:])
    pct = float(fields['ceiling_pct'])
    say(f'{what}: {fields["mb"]} MB of linear memory, {pct}% of the wasm32 ceiling, '
        f'{fields["seconds"]}s')

    if pct > MAX_PCT:
        die(f'{what} took {pct}% of the 4 GiB wasm32 ceiling, over the {MAX_PCT}% gate.\n'
            f'         There is no more address space above it. Raising CXWASM_MAX_PCT\n'
            f'         moves the gate, not the ceiling.')
    if not ratchet:
        return fields

    got = int(fields['bytes'])
    if rebank:
        BANK.write_text(f'{got}\n')
        say(f'--rebank: banked {got} bytes ({fields["mb"]} MB) as the number to beat')
        return fields
    if not BANK.is_file():
        _notes.append('no memory bank yet -- run --rebank to set one; the ratchet is OFF')
        say('  no generated/MEMORY.bank: the RATCHET IS NOT ARMED. --rebank arms it.')
        return fields
    want = int(BANK.read_text().strip())
    delta = 100.0 * (got - want) / want
    say(f'  ratchet: {delta:+.2f}% against the bank ({want} bytes, '
        f'{want / (1024 * 1024):.1f} MB)')
    if delta > DRIFT_PCT:
        die(f'{what} grew {delta:+.2f}% over the banked peak, past the {DRIFT_PCT}% ratchet.\n'
            f'         Memory is this project\'s first priority and this is the whole\n'
            f'         instrument. Find what grew. --rebank is for a number you MEANT\n'
            f'         to change, and it is a deliberate act, not a way past a red run.')
    return fields


def run_module(wasm, src, out, diag=None, raw=False, what='run',
               ratchet=False, rebank=False):
    cmd = ['node', str(TOOLS / 'runwasm.mjs'), str(wasm), str(src), '--out', str(out)]
    if diag:
        cmd += ['--diag', str(diag)]
    if raw:
        cmd += ['--raw']
    r = subprocess.run(cmd, capture_output=True, text=True)
    fields = check_memory(r.stderr, what, ratchet=ratchet, rebank=rebank)
    if r.returncode != 0:
        for line in r.stderr.strip().splitlines()[-6:]:
            say('  ' + line)
        die(f'{what}: the module exited {r.returncode}')
    return fields


def refuse_halt(diag_path, what):
    """CODEGEN-HALTED is the harness refusing to emit for a bad subject.

    It is checked by NAME because that is the marker the rest of the tree
    already refuses on, and because a halt writes a short plausible file
    rather than an empty one -- size is not the tell.
    """
    if not pathlib.Path(diag_path).is_file():
        return
    text = pathlib.Path(diag_path).read_text(errors='replace')
    if 'CODEGEN-HALTED' in text:
        say(text.strip()[:400])
        die(f'{what}: the harness halted on errors in the subject; no module emitted')


def presence(wat, what):
    """Baseline-free: is this the artifact at all, or something plausible?

    A soundness gate is blind to a no-op, and every comparison below is a
    soundness gate. These three facts are true of a whole emitted module and
    of nothing else -- a truncated one fails the last.
    """
    data = pathlib.Path(wat).read_bytes()
    if not data.startswith(b'(module\n'):
        die(f'{what}: does not begin `(module`')
    if b'(func $__start' not in data:
        die(f'{what}: has no entry point')
    if not data.rstrip().endswith(b')'):
        die(f'{what}: does not close -- a truncated module, which is what running '
            f'out of memory mid-emit looks like')
    say(f'{what}: {len(data)} bytes, sha {hashlib.sha256(data).hexdigest()[:16]}')


def road_zig(force):
    """Generation 1 the way it was first reached: through codexzig."""
    head('2  the ZIG road: build a native codexwasm, and emit with it')
    binary = os.environ['CODEXZIG']
    inputs = [SUBJECT, pathlib.Path(binary)]
    if fresh(NATIVE_BIN, inputs, force):
        say(f'{NATIVE_BIN.name} is current -- not rebuilding')
    else:
        say(f'transpiling {SUBJECT.stat().st_size} bytes of compiler+emitter through codexzig...')
        # codexzig writes the PROGRAM to stderr and its diagnostics to stdout.
        with open(SUBJECT, 'rb') as fin, open(NATIVE_ZIG, 'wb') as ferr, \
                open(LOCAL / 'codexwasm.zig.diag', 'wb') as fout:
            subprocess.run([binary], stdin=fin, stdout=fout, stderr=ferr)
        if b'// THE PRELUDE' not in NATIVE_ZIG.read_bytes()[:4_000_000]:
            say(NATIVE_ZIG.read_text(errors='replace')[:300])
            die('codexzig emitted no program')
        say(f'building {NATIVE_BIN.name} from {NATIVE_ZIG.stat().st_size} bytes of zig...')
        r = subprocess.run([str(ZIG), 'build-exe', NATIVE_ZIG.name,
                            f'-femit-bin={NATIVE_BIN.name}'],
                           cwd=LOCAL, capture_output=True, text=True)
        if r.returncode != 0 or not NATIVE_BIN.exists():
            say((r.stdout + r.stderr).strip()[-800:])
            die('zig build-exe refused the emitted program')
        stamp(NATIVE_BIN, inputs)
    say(f'{NATIVE_BIN.name}: {NATIVE_BIN.stat().st_size} bytes')

    say('emitting the subject through the native binary...')
    t0 = time.time()
    with open(SUBJECT, 'rb') as fin, open(WAT, 'wb') as ferr, open(DIAG, 'wb') as fout:
        rc = subprocess.run([str(NATIVE_BIN)], stdin=fin, stdout=fout, stderr=ferr).returncode
    say(f'  {time.time() - t0:.0f}s, exit {rc}')
    refuse_halt(DIAG, 'the native binary')
    presence(WAT, 'generation 1 (zig road)')


def road_self(force):
    """Generation 1 with no zig anywhere: the tracked module does it."""
    head('2  the SELF road: the tracked module compiles the subject')
    say(f'{WASM.name}: {WASM.stat().st_size} bytes, sha {sha(WASM)[:16]}')
    run_module(WASM, SUBJECT, WAT, DIAG, what='generation 1 (self road)')
    refuse_halt(DIAG, 'the tracked module')
    presence(WAT, 'generation 1 (self road)')


def assemble(force):
    head('3  assemble the module')
    if fresh(WASM, [WAT], force):
        say(f'{WASM.name} is current ({WASM.stat().st_size} bytes) -- not reassembling')
        return
    r = subprocess.run(['node', str(TOOLS / 'wat2wasm.mjs'), str(WAT), str(WASM)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        say(r.stderr.strip()[-800:])
        die('wabt refused the module -- the assembler is this emitter\'s type checker')
    say(f'{WASM.name}: {WASM.stat().st_size} bytes, sha {sha(WASM)[:16]}')
    stamp(WASM, [WAT])


def fixed_point(mem, prove_gate=False, rebank=False):
    """The invariant, and the measurement that goes with it.

    `mem` is filled in rather than returned because the peak this build
    reports is THIS run's -- the subject through the module -- and not the
    largest number any stage happened to reach. PROVENANCE says which.
    """
    head('4  THE FIXED POINT')
    say('the module compiles the source that produced it:')
    say(f'  {WASM.name}  <  {SUBJECT.name}   ->  a WAT that must equal {WAT.name}')
    mem.update(run_module(WASM, SUBJECT, GEN2_WAT, GEN2_DIAG, what='generation 2',
                          ratchet=True, rebank=rebank))
    refuse_halt(GEN2_DIAG, 'generation 2')
    presence(GEN2_WAT, 'generation 2')

    if prove_gate:
        # BOX checklist, Before-11: a comparison whose every row reads `ok`
        # has never executed its own mismatch branch. Perturb by the smallest
        # amount that must fail, confirm RED, and put it back.
        say()
        say('--prove-gate: flipping one byte of generation 2 to show the gate fires')
        data = bytearray(GEN2_WAT.read_bytes())
        data[len(data) // 2] ^= 0x01
        GEN2_WAT.write_bytes(bytes(data))

    a, b = WAT.read_bytes(), GEN2_WAT.read_bytes()
    if a == b:
        if prove_gate:
            die('--prove-gate flipped a byte and the comparison still said equal. '
                'The gate does not work and every green run above it means nothing.')
        say(f'IDENTICAL -- {len(a)} bytes, both ways')
        return True
    say(f'DIFFERS: generation 1 is {len(a)} bytes, generation 2 is {len(b)}')
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            say(f'  first difference at byte {i}')
            say(f'    gen 1: {a[max(0, i - 40):i + 40]!r}')
            say(f'    gen 2: {b[max(0, i - 40):i + 40]!r}')
            break
    else:
        say('  one is a prefix of the other')
    if prove_gate:
        say('the gate FIRES -- restoring generation 2 and calling this a pass')
        GEN2_WAT.write_bytes(a)
        return True
    return False


def run_sample():
    head('5  compile and run a real program')
    # The fixed point says the emitter agrees with itself. It cannot, alone,
    # say the emitter does anything -- a "compiler" emitting a program that
    # printed its own input back would satisfy it perfectly. This is the
    # answer to that: a program whose output is known, through the artifact.
    # None of the numbers it prints appear in its source; 92 is the count of
    # eight-queens solutions and the module works it out by backtracking.
    r = subprocess.run([str(PWSH), '-NoProfile', '-File',
                        str(cobblestone.root() / 'build' / 'bundle-app.ps1'),
                        '-Src', str(SAMPLE), '-Out', str(SAMPLE_UNIT)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not SAMPLE_UNIT.is_file():
        say((r.stdout + r.stderr).strip()[-400:])
        die(f'could not bundle {SAMPLE.name}')
    run_module(WASM, SAMPLE_UNIT, SAMPLE_WAT, what=f'{SAMPLE.name} -> WAT')
    presence(SAMPLE_WAT, SAMPLE_WAT.name)
    r = subprocess.run(['node', str(TOOLS / 'wat2wasm.mjs'), str(SAMPLE_WAT), str(SAMPLE_WASM)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        say(r.stderr.strip()[-400:])
        die('wabt refused the sample module')
    run_module(SAMPLE_WASM, SAMPLE, SAMPLE_OUT, raw=True, what=f'{SAMPLE.name} running')
    got = SAMPLE_OUT.read_text(errors='replace').strip().splitlines()
    want = SAMPLE_EXPECTED.read_text().strip().splitlines()
    for line in got:
        say('  > ' + line)
    if got == want:
        say(f'MATCHES {SAMPLE_EXPECTED.name} -- all {len(want)} lines')
        return True
    say(f'DIFFERS from {SAMPLE_EXPECTED.name}:')
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else '<nothing>'
        w = want[i] if i < len(want) else '<nothing>'
        if g != w:
            say(f'  line {i + 1}: got {g!r}, want {w!r}')
    return False


def write_provenance(root, road, mem):
    head('6  provenance')
    lines = [
        'codex-wasm-transpiler -- what produced the artifacts beside this file.',
        '',
        'THE AXES. Anything that can change a byte of generated/codexwasm.wat is',
        'named here. A build that cannot say what it measured is not evidence, and',
        'the fixed point cannot supply the difference -- it holds just as well',
        'against the wrong source.',
        '',
        f'built            {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}',
        f'road             {road}',
        f'host             {os.uname().nodename}  node '
        f'{subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()}',
        '',
        f'COBBLESTONE_ROOT {root}',
        f'  revision       {cobblestone.revision(root)}',
        '',
        f'subject          {SUBJECT.name}  {SUBJECT.stat().st_size} bytes',
        f'  sha256         {sha(SUBJECT)}',
        f'artifact         {WAT.name}  {WAT.stat().st_size} bytes',
        f'  sha256         {sha(WAT)}',
        f'assembled        {WASM.name}  {WASM.stat().st_size} bytes',
        f'  sha256         {sha(WASM)}',
    ]
    if road in ('zig', 'both'):
        binary = os.environ.get('CODEXZIG', '')
        lines += ['',
                  f'codexzig         {binary}',
                  f'  sha256         {sha(binary) if binary else "-"}',
                  '  NOTE           the zig road puts codexzig in the trusted base. Its own',
                  '                 provenance is its repository\'s; this records only which',
                  '                 binary ran.']
    lines += ['',
              'MEMORY -- the first priority, measured rather than estimated.',
              f'  peak           {mem.get("mb", "?")} MB of linear memory',
              f'  ceiling        {mem.get("ceiling_pct", "?")}% of wasm32\'s hard 4 GiB',
              f'  ceiling gate   refuse above {MAX_PCT}% -- will it die',
              f'  ratchet        refuse more than {DRIFT_PCT}% over MEMORY.bank -- did it get worse',
              f'  bank           {BANK.read_text().strip() if BANK.is_file() else "not set"}']
    if _notes:
        lines += ['', 'NOTES'] + [f'  - {n}' for n in _notes]
    (GEN / 'PROVENANCE').write_text('\n'.join(lines) + '\n')
    for line in lines:
        say('  ' + line)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--road', choices=('self', 'zig', 'both'), default=None,
                    help='how generation 1 is produced (default: self if the module exists)')
    ap.add_argument('--force', action='store_true', help='rebuild every stage')
    ap.add_argument('--check-only', action='store_true',
                    help='check the fixed point against what is on disk')
    ap.add_argument('--prove-gate', action='store_true',
                    help='perturb generation 2 and require the comparison to FAIL')
    ap.add_argument('--no-sample', action='store_true', help='skip stage 5')
    ap.add_argument('--rebank', action='store_true',
                    help='bank this run\'s peak memory as the number the ratchet reads')
    args = ap.parse_args()

    road = args.road or ('self' if WASM.is_file() else 'zig')
    say(f'road: {road}' + ('' if args.road else '  (default -- pass --road to choose)'))
    root = preflight(road)

    if not args.check_only:
        bundle(args.force)
        if road in ('zig', 'both'):
            road_zig(args.force)
            zig_wat = WAT.read_bytes()
        if road in ('self', 'both'):
            if road == 'both':
                # The roads are interchangeable and this is where that is
                # checked: the tracked module and the native binary emit the
                # same bytes for the same subject, on two different machines.
                head('2b  the SELF road, for comparison with the zig road')
                run_module(WASM, SUBJECT, GEN2_WAT, what='the self road')
                if GEN2_WAT.read_bytes() != zig_wat:
                    die('THE ROADS DISAGREE. The native binary and the wasm module '
                        'emitted different bytes for the same subject -- which is a '
                        'defect in one of the two, and the source is the same source.')
                say('the two roads agree, byte for byte')
            else:
                road_self(args.force)
        assemble(args.force)
    else:
        for f in (SUBJECT, WAT, WASM):
            if not f.is_file():
                die(f'--check-only, but {f.name} is missing')

    mem = {}
    ok = fixed_point(mem, args.prove_gate, args.rebank)
    sample_ok = True
    if not args.no_sample:
        sample_ok = run_sample()

    if not args.check_only:
        write_provenance(root, road, mem)

    head('verdict')
    say(f'fixed point   {"HOLDS" if ok else "BROKEN"}')
    say(f'sample        {"matches" if sample_ok else "DIFFERS"}')
    for n in _notes:
        say(f'note          {n}')
    return 0 if (ok and sample_ok) else 1


if __name__ == '__main__':
    sys.exit(main())
