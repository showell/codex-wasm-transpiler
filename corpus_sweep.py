#!/usr/bin/env python3
"""Put a whole corpus of Codex programs through the emitter, and grade it.

    ./corpus_sweep.py                    # emit, assemble, run, compare
    ./corpus_sweep.py --emit-only        # stop after wat2wasm
    ./corpus_sweep.py --corpus <dir>     # default: the ladder's corpus/

THIRTY PROGRAMS IS NOT A BASIS FOR A COMPILER. Everything else in this
repository is checked against the compiler's own source, twenty-nine units of
a ported game, and two samples -- all of them chosen by what we happened to be
working on. This runs 580, chosen by somebody else.

THREE GRADES, AND THE MIDDLE ONE IS THE POINT.

1. EMIT. Every program produces a module or it does not. Nothing has ever
   failed here.

2. ASSEMBLE. `wat2wasm` is this emitter's type checker and it sees a class of
   defect nothing else does: a builtin the plug has no arm for is NOT emitted
   as a bad call -- the name is treated as a value, reaches the funcref path,
   and comes out as `call_indirect` against a local nothing declared. A grep
   cannot find that. The assembler names it and the line.

3. RUN, against the hand-verified `.expected` beside each program in the
   checkout's `codex/test`. This is where a WRONG ANSWER shows up rather than
   a refused module, and it is the grade worth the wall-clock.

THE CORPUS IS IR TEXT, which is what `codex/plugs/wasm/WasmPlug.codex`
consumes, so nothing is compiled here: `source/IrHarness.codex` is a driver
that reads IR from stdin and emits. That is the whole reason this is minutes
rather than hours.

WHAT A TRAP MEANS. Programs naming hardware -- `port-out-32`, `read-mmio-32`,
gpu, net, uefi -- emit `(unreachable) (; no wasm form for X ;)` deliberately,
so they assemble and then trap. A trap here is the plug declining, not the
plug failing, and the count is expected to be large.
"""
import argparse
import collections
import json
import os
import pathlib
import re
import subprocess
import sys
import time

import cobblestone

HERE = pathlib.Path(__file__).resolve().parent
SOURCE, TOOLS, LOCAL = HERE / 'source', HERE / 'tools', HERE / 'generated' / 'local'
PWSH = pathlib.Path.home() / '.local' / 'pwsh' / 'pwsh'
ZIG = pathlib.Path(os.environ.get('ZIG', pathlib.Path.home() / 'zig-0.16.0' / 'zig'))
LADDER = pathlib.Path(os.environ.get('CXWASM_LADDER',
                                     pathlib.Path.home() / 'showell_repos' / 'codex-zig-ladder'))
_t0 = time.time()


def say(m=''):
    print(f'[{time.time() - _t0:6.1f}s] {m}', flush=True)


def expected_text(name, tests):
    """The .expected as the comparison sees it.

    One home for the normalisation, copied from the ladder's corpus_run.py: 76
    of the depot's .expected files open with one 0x01 the console capture
    wrote, and a subset of exactly those use CRLF.
    """
    for exp in tests.rglob(f'{name}.expected'):
        want = exp.read_text(errors='replace').replace('\r', '')
        return want[1:] if want.startswith('\x01') else want
    return None


def build_ir_binary(out):
    """A driver that reads IR text and emits, built the fast way."""
    subject = LOCAL / 'irsweep-subject.codex'
    r = subprocess.run([str(PWSH), '-NoProfile', '-File', str(SOURCE / 'bundle_codexwasm.ps1'),
                        '-OutFile', str(subject), '-Harness', str(SOURCE / 'IrHarness.codex')],
                       capture_output=True, text=True)
    if r.returncode != 0 or not subject.is_file():
        raise SystemExit((r.stdout + r.stderr).strip()[-500:])
    codexzig = os.environ.get('CODEXZIG')
    if not codexzig:
        raise SystemExit('corpus_sweep needs $CODEXZIG to build its driver')
    zig_src = LOCAL / 'irsweep.zig'
    with open(subject, 'rb') as fin, open(zig_src, 'wb') as ferr:
        subprocess.run([codexzig], stdin=fin, stdout=subprocess.DEVNULL, stderr=ferr)
    if b'// THE PRELUDE' not in zig_src.read_bytes()[:4_000_000]:
        raise SystemExit('codexzig emitted no program for the IR driver')
    r = subprocess.run([str(ZIG), 'build-exe', zig_src.name, f'-femit-bin={out.name}'],
                       cwd=LOCAL, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit((r.stdout + r.stderr).strip()[-500:])
    say(f'{out.name}: {out.stat().st_size} bytes')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--corpus', default=str(LADDER / 'corpus'))
    ap.add_argument('--emit-only', action='store_true')
    ap.add_argument('--reuse', action='store_true', help='reuse the IR driver binary')
    args = ap.parse_args()
    corpus = pathlib.Path(args.corpus)
    irs = sorted(corpus.glob('*.ir'))
    if not irs:
        raise SystemExit(f'no .ir files in {corpus}')
    tests = cobblestone.root() / 'codex' / 'test'
    work = LOCAL / 'sweep'
    work.mkdir(parents=True, exist_ok=True)
    binary = LOCAL / 'codexwasm-ir'
    if not (args.reuse and binary.is_file()):
        build_ir_binary(binary)

    say(f'1  emitting {len(irs)} programs')
    emitted = []
    for f in irs:
        wat = work / f'{f.stem}.wat'
        with open(f, 'rb') as fin, open(wat, 'wb') as ferr:
            rc = subprocess.run([str(binary)], stdin=fin, stdout=subprocess.DEVNULL,
                                stderr=ferr, timeout=300).returncode
        (emitted if rc == 0 and wat.stat().st_size > 100 else []).append(f.stem)
    say(f'   emitted a module: {len(emitted)} of {len(irs)}')

    say('2  assembling')
    (work / 'names.json').write_text(json.dumps(emitted))
    r = subprocess.run(['node', '--max-old-space-size=6000',
                        str(TOOLS / 'assemble_many.mjs'), str(work)],
                       capture_output=True, text=True)
    say('   ' + (r.stdout.strip().splitlines() or ['?'])[0])
    refused = {n for n, _ in json.loads((work / 'asm-fails.json').read_text())}
    ok = [n for n in emitted if n not in refused]
    if args.emit_only:
        return report_refusals(work, refused)

    say(f'3  running the {len(ok)} that assembled, against .expected')
    empty = LOCAL / 'empty.in'
    empty.write_bytes(b'')
    grades = collections.Counter()
    differ = []
    for n in ok:
        want = expected_text(n, tests)
        if want is None:
            grades['no .expected'] += 1
            continue
        out = work / f'{n}.out'
        p = subprocess.run(['node', str(TOOLS / 'runwasm.mjs'), str(work / f'{n}.wasm'),
                            str(empty), '--out', str(out), '--raw'],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            grades['TRAP (a deliberate refusal, or a real one)' if 'CXWASM-TRAP' in p.stderr
                   else f'exit {p.returncode}'] += 1
            continue
        got = out.read_text(errors='replace')
        if got.strip() == want.strip():
            grades['MATCH'] += 1
        else:
            grades['DIFFER'] += 1
            differ.append(n)
    say()
    for k, v in grades.most_common():
        say(f'   {v:>4}  {k}')
    if differ:
        say(f'\n   DIFFER: {" ".join(differ)}')
    report_refusals(work, refused)
    return 0


def report_refusals(work, refused):
    if not refused:
        return 0
    say(f'\n   {len(refused)} refused by the assembler:')
    by = collections.Counter()
    for n, e in json.loads((work / 'asm-fails.json').read_text()):
        m = re.search(r'error: ([^|]{0,54})', e)
        by[(m.group(1).strip() if m else e[:50])] += 1
    for k, v in by.most_common(10):
        say(f'     {v:>3}  {k}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
