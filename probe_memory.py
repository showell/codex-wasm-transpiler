#!/usr/bin/env python3
"""WHERE THE 3.7 GB GOES, phase by phase.

    ./probe_memory.py              # instrument, build, measure, print the table
    ./probe_memory.py --keep       # and leave the probe binary for another run

The bump heap never reclaims, so **`__heap-save` IS the running total of
everything allocated since the process started**: read it between two phases
and the difference is exactly what that phase allocated, with no sampling and
no profiler. That is the whole instrument, and it is exact in a way a sampling
profiler is not.

WHY THIS IS THE FIRST THING TO BUILD ON MEMORY. `tools/runwasm.mjs` already
splits the total two ways for free -- the driver writes its diagnostics
immediately before it emits, so the first `fd_write` is the front end's last
moment -- and that says the front end retains 2,852 MB of the 3,716 MB and
spends 16.5 s of the 19.5 s. Everything that matters is inside that number and
nothing outside it can be attacked. This opens it.

THE MARKS ARE WRITTEN IN MECHANICALLY, not by hand, and the pass refuses if
the driver has a binding it did not account for. A dropped phase is INVISIBLE
in the output -- the table is simply shorter and the missing cost folds
silently into the row above it. safari-codex's `harness/mem_probe.py` found
exactly that in its own pattern, where the depth machinery had been dead code
for a year because the regex could not match `else let`.

IT MEASURES THE NATIVE BINARY, and that is a deliberate choice rather than a
convenience. The frontier is the CODEX program's own heap pointer, so the
numbers are a property of the program and not of the plug that emitted it --
safari measured the front-end rows identical to the byte between the zig and
wasm arms. The native arm is one `zig build-exe` instead of an assemble step,
and the peak that matters is still read from the wasm run.

WHAT THIS CANNOT SEE. The frontier is what SURVIVES a phase. Emission brackets
every definition in `__heap-save`/`__heap-restore`, so its cost is the maximum
over definitions and the frontier comes back down before the next mark: the
EMIT row is a floor, not a peak. The peak is the 864 MB the runner reports
above the front end's retention.
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

HARNESS = SOURCE / 'CodexWasmHarness.codex'
SUBJECT = GEN / 'codexwasm-subject.codex'
PROBE_HARNESS = LOCAL / 'CodexWasmHarnessProbe.codex'
PROBE_SUBJECT = LOCAL / 'probe-subject.codex'
PROBE_ZIG = LOCAL / 'codexwasm-probe.zig'
PROBE_BIN = LOCAL / 'codexwasm-probe'

# The deck prologue is the baseline rather than a phase. `deck-adv` IS marked
# and the three before it are not, because that mark is the baseline itself:
# it is taken after the 512 MB deck reservation and before the front end
# starts, so every later row is measured from a frontier that already carries
# the reservation and tokenize's own cost is visible.
#
# Marking all four instead cost exactly that: the first row became the
# baseline, so `toks` read 0.0 MB and its allocation folded into a number
# nothing printed. That is the failure this file's docstring warns about,
# committed while writing the warning.
PROLOGUE = ('mountain-base', 'deck-base', 'deck-set')

PROF = '''
Section: Profile

 Written by probe_memory.py. `__heap-save` is the bump frontier, and the bump
 heap never reclaims, so the value at a mark is the running total of
 everything allocated so far.

 The newline is a `list-push ... 10` and not a literal, and that is not a
 style choice: A TEXT LITERAL OPENED AT THE END OF A LINE LEXES AS AN EMPTY
 ONE, silently.

  prof-line : Text, Integer -> List Integer
  prof-line (n) (v) = list-push (text-to-utf8-bytes ("PROF " & n & " " & show v)) 10
'''


def say(msg=''):
    print(msg, flush=True)


def instrument(text):
    """Insert `in let hp-N = __heap-save` after every phase of the driver.

    A `let` in this driver is one line EXCEPT the `IRTextMeta` literal, which
    is seven, so bracket depth decides when a binding has closed. Marking
    inside the literal would not compile, and skipping it by line number would
    break the next time that record gains a field.
    """
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith('  opening :'))
    out, marks, skipped, depth, pending = lines[:start], [], [], 0, None
    # `else let` as well as `in let`: the IRTextMeta binding opens the else arm
    # of the halt gate, and a pattern that misses it does not fail -- it
    # silently drops the phase and shortens the table.
    binding = re.compile(r'^(\s+)(?:in |else )?let ([a-z][a-z0-9-]*) = ')
    for line in lines[start:]:
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
        if name in PROLOGUE:
            skipped.append(name)
        else:
            marks.append(name)
            out.append(f'{indent}in let hp-{len(marks)} = __heap-save')
        pending = None

    loose = re.findall(r'\blet ([a-z][a-z0-9-]*) = ', '\n'.join(lines[start:]))
    missed = [n for n in loose if n not in marks and n not in skipped]
    if missed:
        raise SystemExit('probe_memory: the driver has bindings this pass did not mark, '
                         f'so the table would silently omit them: {missed}')

    text = '\n'.join(out) + '\n'
    report = ' & '.join(f'prof-line "{n}" hp-{i + 1}' for i, n in enumerate(marks))
    # The report goes out on write-binary (stdout on the native arm) because
    # the emitted module is on stderr there. The second call sits AFTER the
    # emit, so the last row measures emission -- as a floor, see the module
    # docstring.
    body = re.search(r'(    in act\n)(.*?)(\n    end\n  end)', text, re.S)
    inner = body.group(2).splitlines()
    text = text[:body.start(2)] + '\n'.join(
        [inner[0], f'      write-binary ({report})'] + inner[1:]
        + ['      write-binary (prof-line "EMIT" __heap-save)']) + text[body.end(2):]
    return text + PROF, marks


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--keep', action='store_true', help='leave the probe binary in place')
    ap.add_argument('--reuse', action='store_true', help='reuse an existing probe binary')
    args = ap.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    root = cobblestone.root()
    if not SUBJECT.is_file():
        raise SystemExit(f'no {SUBJECT.name}; run ./build.py first')

    if not (args.reuse and PROBE_BIN.is_file()):
        probed, marks = instrument(HARNESS.read_text())
        PROBE_HARNESS.write_text(probed)
        say(f'instrumented {len(marks)} phases into {PROBE_HARNESS.name}')

        r = subprocess.run([str(PWSH), '-NoProfile', '-File',
                            str(SOURCE / 'bundle_codexwasm.ps1'),
                            '-OutFile', str(PROBE_SUBJECT),
                            '-Harness', str(PROBE_HARNESS)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not PROBE_SUBJECT.is_file():
            say((r.stdout + r.stderr).strip()[-600:])
            raise SystemExit('the bundler refused the probed harness')
        say(f'{PROBE_SUBJECT.name}: {PROBE_SUBJECT.stat().st_size} bytes')

        codexzig = os.environ.get('CODEXZIG')
        if not codexzig:
            raise SystemExit('probe_memory needs $CODEXZIG to build the probe binary')
        say('transpiling the probe through codexzig...')
        with open(PROBE_SUBJECT, 'rb') as fin, open(PROBE_ZIG, 'wb') as ferr:
            subprocess.run([codexzig], stdin=fin, stdout=subprocess.DEVNULL, stderr=ferr)
        if b'// THE PRELUDE' not in PROBE_ZIG.read_bytes()[:4_000_000]:
            say(PROBE_ZIG.read_text(errors='replace')[:300])
            raise SystemExit('codexzig emitted no program for the probe')
        say(f'building {PROBE_BIN.name}...')
        r = subprocess.run([str(ZIG), 'build-exe', PROBE_ZIG.name,
                            f'-femit-bin={PROBE_BIN.name}'],
                           cwd=LOCAL, capture_output=True, text=True)
        if r.returncode != 0:
            say((r.stdout + r.stderr).strip()[-600:])
            raise SystemExit('zig refused the probe')

    say(f'measuring on {SUBJECT.name} ({SUBJECT.stat().st_size} bytes)...')
    t0 = time.time()
    with open(SUBJECT, 'rb') as fin:
        r = subprocess.run([str(PROBE_BIN)], stdin=fin,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    say(f'  {time.time() - t0:.0f}s')

    rows = [(m.group(1).decode(), int(m.group(2)))
            for m in re.finditer(rb'PROF (\S+) (\d+)', r.stdout)]
    if not rows:
        raise SystemExit('the probe printed no PROF rows')

    say()
    say(f'{"phase":<22}{"retained MB":>13}{"this phase":>13}{"% of total":>12}')
    say('-' * 60)
    base = rows[0][1]
    total = rows[-1][1] - base
    prev = base
    for name, v in rows:
        d = v - prev
        say(f'{name:<22}{(v - base) / 1048576:>13.1f}{d / 1048576:>13.1f}'
            f'{100.0 * d / total:>11.1f}%')
        prev = v
    say('-' * 60)
    say(f'{"TOTAL":<22}{total / 1048576:>13.1f}')
    say()
    say('Rows are the frontier AFTER that phase; "this phase" is the difference,')
    say('which is exactly what it allocated. EMIT is a floor, not a peak --')
    say('emission restores the heap between definitions.')
    if not args.keep and not args.reuse:
        PROBE_BIN.unlink(missing_ok=True)
        PROBE_ZIG.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
