#!/usr/bin/env python3
"""WHERE EMISSION'S MEMORY GOES, inside `emit-wasm-chapter-stream`.

    ./probe_emit.py

`probe_memory.py` stops at the emitter's front door: it reports one EMIT row,
and that row is the largest number left that this project can act on alone.
This opens it.

Same instrument, one level down. The bump heap never reclaims, so the frontier
`__heap-save` returns IS the running total, and the difference between two
marks is exactly what the step between them allocated. The marks are printed
as WAT COMMENTS -- `;; PROF <name> <frontier>` -- which needs no effect this
function does not already have and cannot be confused with the module, because
every other line of it is not a comment.

WHAT TO EXPECT, AND WHY THE ANSWER IS NOT OBVIOUS. Emission streams: every
definition is bracketed in `__heap-save`/`__heap-restore`, so the frontier
comes back down between definitions and `wasm-stream-defs` should retain
almost nothing. Everything the row costs is therefore in the bindings ABOVE
the act block, which are computed once and held for the whole stream -- the
string table, the arity map, the runtime text, the data sections, the type
definitions, and two import scans. Which of those it is has never been
measured.
"""
import argparse
import os
import pathlib
import re
import subprocess
import sys
import time

import cobblestone

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / 'source'
GEN = HERE / 'generated'
LOCAL = GEN / 'local'
PWSH = pathlib.Path.home() / '.local' / 'pwsh' / 'pwsh'
ZIG = pathlib.Path(os.environ.get('ZIG', pathlib.Path.home() / 'zig-0.16.0' / 'zig'))

SUBJECT = GEN / 'codexwasm-subject.codex'
PROBE_EMITTER = LOCAL / 'WasmEmitterProbe.codex'
PROBE_SUBJECT = LOCAL / 'emitprobe-subject.codex'
PROBE_ZIG = LOCAL / 'codexwasm-emitprobe.zig'
PROBE_BIN = LOCAL / 'codexwasm-emitprobe'

FN = '  emit-wasm-chapter-stream (m) (type-defs) ='


def say(m=''):
    print(m, flush=True)


def mark(name):
    return f'    print-uni (";; PROF {name} " & integer-to-text __heap-save & "\\n")\n'


def instrument(text):
    """Mark every binding of the emitter's entry, and every step of its act."""
    start = text.index(FN)
    end = text.index('\n   end\n', start) + len('\n   end\n')
    body, marks = text[start:end], []
    out, depth, pending = [], 0, None
    binding = re.compile(r'^(\s+)(?:in )?let ([a-z][a-z0-9-]*) = ')
    for line in body.splitlines():
        if line.strip() == 'in act':
            out.append(line)
            break
        out.append(line)
        if pending is None:
            m = binding.match(line)
            if not m:
                continue
            pending = m
        depth += line.count('{') + line.count('[') - line.count('}') - line.count(']')
        if depth > 0:
            continue
        indent, name = pending.group(1), pending.group(2)
        marks.append(name)
        out.append(f'{indent}in let ehp-{len(marks)} = __heap-save')
        pending = None

    loose = re.findall(r'\blet ([a-z][a-z0-9-]*) = ', body[:body.index('in act')])
    missed = [n for n in loose if n not in marks]
    if missed:
        raise SystemExit(f'probe_emit: bindings this pass did not mark: {missed}')

    # The act block: a mark after every statement, so the streaming step and
    # the three that print already-built text are told apart.
    act = body[body.index('in act') + len('in act'):]
    stmts = [l for l in act.splitlines() if l.strip() and l.strip() != 'end']
    inner = ['    print-uni (";; PROF ' + n + ' " & integer-to-text ehp-'
             + str(i + 1) + ' & "\\n")' for i, n in enumerate(marks)]
    for s in stmts:
        inner.append(s)
        label = re.sub(r'[^a-z0-9-]+', '-', s.strip().split('(')[0].strip().lower()).strip('-')
        inner.append(mark('act-' + (label or 'step')).rstrip('\n'))
    rebuilt = '\n'.join(out) + '\n' + '\n'.join(inner) + '\n   end\n'
    return text[:start] + rebuilt + text[end:], marks


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    if not SUBJECT.is_file():
        raise SystemExit('run ./build.py first')
    src = cobblestone.root() / 'codex' / 'plugs' / 'wasm' / 'WasmEmitter.codex'
    probed, marks = instrument(src.read_text())
    PROBE_EMITTER.write_text(probed)
    say(f'marked {len(marks)} bindings plus every act step')

    r = subprocess.run([str(PWSH), '-NoProfile', '-File', str(SOURCE / 'bundle_codexwasm.ps1'),
                        '-OutFile', str(PROBE_SUBJECT), '-Emitter', str(PROBE_EMITTER)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not PROBE_SUBJECT.is_file():
        say((r.stdout + r.stderr).strip()[-600:]); raise SystemExit('bundler refused')

    codexzig = os.environ.get('CODEXZIG')
    if not codexzig:
        raise SystemExit('probe_emit needs $CODEXZIG')
    say('transpiling the probe...')
    with open(PROBE_SUBJECT, 'rb') as fin, open(PROBE_ZIG, 'wb') as ferr:
        subprocess.run([codexzig], stdin=fin, stdout=subprocess.DEVNULL, stderr=ferr)
    if b'// THE PRELUDE' not in PROBE_ZIG.read_bytes()[:4_000_000]:
        say(PROBE_ZIG.read_text(errors='replace')[:400]); raise SystemExit('no program')
    say('building...')
    r = subprocess.run([str(ZIG), 'build-exe', PROBE_ZIG.name, f'-femit-bin={PROBE_BIN.name}'],
                       cwd=LOCAL, capture_output=True, text=True)
    if r.returncode != 0:
        say((r.stdout + r.stderr).strip()[-600:]); raise SystemExit('zig refused')

    say(f'measuring on {SUBJECT.name}...')
    t0 = time.time()
    with open(SUBJECT, 'rb') as fin:
        r = subprocess.run([str(PROBE_BIN)], stdin=fin,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    say(f'  {time.time() - t0:.0f}s')
    rows = [(m.group(1).decode(), int(m.group(2)))
            for m in re.finditer(rb';; PROF (\S+) (\d+)', r.stderr)]
    if not rows:
        raise SystemExit('no PROF rows; the probe printed nothing')

    say()
    say(f'{"step":<34}{"this step MB":>14}{"% of emit":>11}')
    say('-' * 60)
    base, total, prev = rows[0][1], rows[-1][1] - rows[0][1], rows[0][1]
    for name, v in rows:
        d = v - prev
        say(f'{name:<34}{d / 1048576:>14.1f}{100.0 * d / total if total else 0:>10.1f}%')
        prev = v
    say('-' * 60)
    say(f'{"TOTAL from the first mark":<34}{total / 1048576:>14.1f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
