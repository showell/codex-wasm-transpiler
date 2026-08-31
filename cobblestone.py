"""The sister checkout: where it is, and which one it is.

This repository holds no Codex source. Every chapter it bundles is read
out of a Cobblestone checkout named by $COBBLESTONE_ROOT, and every
artifact under generated/ is stamped with the revision it was read from. A
build that cannot say which checkout it measured is not evidence.

The variable is deliberately NOT $CODEX_ROOT. That one belongs to the
codex-zig-ladder, which moves its checkout's HEAD between branches and
pinned Updates all day as part of how it works. Sharing the variable would
mean this repository's answer depended on what the ladder happened to be
doing, and a fixed point built from a checkout nobody chose is worth
nothing. Point this one at a checkout that stays where it is put.
"""

import os
import pathlib
import subprocess

# The compiler's driver. A directory holding this is a checkout; a
# directory not holding it is not, whatever it is called.
MARKER = pathlib.Path('codex') / 'compiler' / 'opening.codex'

HERE = pathlib.Path(__file__).resolve().parent


class NoCheckout(RuntimeError):
    """$COBBLESTONE_ROOT is unset, or does not name a checkout."""


def root():
    """The checkout to build from. Raises rather than guessing.

    There is no search and no fallback. A build silently pointed at the
    wrong checkout would emit zig for a compiler nobody named, which is
    the one failure the fixed point cannot catch -- it holds just as well
    against the wrong source.
    """
    named = os.environ.get('COBBLESTONE_ROOT')
    if not named:
        raise NoCheckout(
            'COBBLESTONE_ROOT is unset. Point it at a Cobblestone checkout '
            'that stays put -- not the ladder\'s, whose HEAD moves:\n'
            '    export COBBLESTONE_ROOT=~/showell_repos/cobblestone-pin')
    path = pathlib.Path(named).expanduser().resolve()
    if not (path / MARKER).is_file():
        raise NoCheckout(f'COBBLESTONE_ROOT={named} holds no {MARKER}')
    return path


def revision(path):
    """`<short-sha> <subject>`, or a plain note when git cannot say.

    Dirty is reported, because a build from a modified checkout is not
    reproducible from the sha alone and the artifact should say so.
    """
    def git(*args):
        r = subprocess.run(('git', '-C', str(path)) + args,
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    sha = git('rev-parse', '--short', 'HEAD')
    if sha is None:
        return 'not a git checkout'
    subject = git('log', '-1', '--format=%s') or ''
    dirty = ' +dirty' if git('status', '--porcelain') else ''
    return f'{sha}{dirty}  {subject}'[:100]


if __name__ == '__main__':
    # The PowerShell bundlers ask through this, so the variable name, the
    # marker and the error text have exactly one home.
    print(root())
