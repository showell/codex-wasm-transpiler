# The transpiler subject: the hosted compiler's chapter set, plus the WASM
# emitter, plus the IR text parser, behind CodexWasmHarness.
#
# THE COMPILER'S CHAPTERS COME FROM THE CHECKOUT: build/compiler-order.txt, in
# its order, as codex-zig-transpiler's bundler does since U62. Upstream's
# concat-codex-self.ps1 refuses any .codex under codex/compiler without a row
# there, so it is the whole compiler by construction, the driver included.
# Only what is left out is named here, each with its reason.
#
# This used to be a hand-kept copy of codex-zig-transpiler's list, "a
# deliberate copy, and the drift is accepted", on the argument that calling a
# SIBLING's bundler would couple this subject to a file two projects away.
# That argument stands and is not what this does: compiler-order.txt is
# upstream's own file, in the checkout every chapter here is already read from.
# U62 added IR/ConstShare and IR/MethodSpecialization, read without a cite by
# chapters the copy named, and the copy was the thing that had to be edited.

# Add-PlugChapter, Resolve-PlugForewords and Bundle-PlugSource come from the
# CHECKOUT's own plug-build-lib.ps1. Bundling resolves foreword cites and
# assembles quires by upstream's rules, and a reimplementation here would be a
# fork that drifts silently -- which is a different thing from the copy above,
# because a chapter LIST breaks loudly and a bundling RULE does not.
#
# IRTextParser IS carried, and that is load-bearing rather than incidental:
# the harness emits IR text and parses it straight back, because the wire
# DERIVES what the AST does not carry. CodexWasmHarness.codex has the argument.

param([string]$OutFile, [string]$Harness, [string]$Emitter)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = (& python3 (Join-Path $here '..' 'cobblestone.py')).Trim()

. "$repo/codex/plugs/common/plug-build-lib.ps1"

$lines = [System.Collections.Generic.List[string]]::new()

# CCE is NOT listed. plug-build-lib carries a foreword chapter automatically
# once something cites it, and this bundle cites it, so listing it as well
# puts CCE in twice -- once as Foreword--CCE and once as Parsmi--CCE, two
# quires holding every definition in it. Duplicate VALUES only warn (CDX3006,
# easy to read past); CharClass is a TYPE, and a duplicate type is CDX3001, a
# hard error. ListUtils is omitted for the same reason: Core/Collections.codex
# cites Foreword chapter ListUtils.
#
# The foreword chapters opening.codex cites (Maybe, Wrap64, Fat16, ImportGate,
# FactDisk) are NOT listed either, for the same reason as CCE: plug-build-lib
# brings a cited foreword chapter as Foreword--<name>, and listed here each
# was Parsmi--<name> as well (codex-zig-transpiler's bundler has the account).
$leftOut = @{
    # BootPaintStubs.codex stands in, below, and says why it is a stub.
    'codex/compiler/Core/BootPaint.codex' = $true
    # The harness is the entry point: it defines `opening`.
    'codex/compiler/EntryPoint.codex' = $true
}
$orderFile = Join-Path $repo 'build/compiler-order.txt'
$order = Get-Content $orderFile | ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $_ -replace '\\', '/' }
foreach ($known in $leftOut.Keys) {
    if ($order -notcontains $known) { throw "$known has no row in $orderFile -- upstream moved it; read their change before editing this list" }
}
foreach ($ch in $order) {
    if ($leftOut.ContainsKey($ch)) { continue }
    Add-PlugChapter -Lines $lines -Path (Join-Path $repo $ch) -Quire 'Parsmi'
}
Add-PlugChapter -Lines $lines -Path (Join-Path $repo 'codex/plugs/common/IRTextParser.codex') -Quire 'Parsmi'
# -Emitter is for probe_emit.py, which bundles an INSTRUMENTED copy of the
# emitter. It defaults to the checkout's, so nothing that does not pass it can
# accidentally measure or ship a probe.
$emitterPath = if ($Emitter) { $Emitter } else { Join-Path $repo 'codex/plugs/wasm/WasmEmitter.codex' }
Add-PlugChapter -Lines $lines -Path $emitterPath -Quire 'Parsmi'

# Update 42 gave PhaseAllocator a cite of Codex chapter BootPaint, and a cite
# names a chapter rather than a symbol, so a subject carrying PhaseAllocator
# must answer for one. BootPaintStubs.codex says why it is a stub.
Add-PlugChapter -Lines $lines -Path (Join-Path $here 'BootPaintStubs.codex') -Quire 'Parsmi'
# -Harness is for probe_memory.py, which bundles an INSTRUMENTED copy of the
# driver. It defaults to the real one, so nothing that does not pass it can
# accidentally measure or ship a probe.
$harnessPath = if ($Harness) { $Harness } else { Join-Path $here 'CodexWasmHarness.codex' }
Add-PlugChapter -Lines $lines -Path $harnessPath -Quire 'Parsmi'

# All 14 pages of the X86-64 Code Generator chapter are present, so the
# 'Page N of 14' trailers stand as upstream wrote them. Upstream rewrites
# them because its smaller subjects carry a SUBSET of the pages; this one
# never does, so there is nothing to renumber.

$preLines = Resolve-PlugForewords $lines
Bundle-PlugSource -PreLines $preLines -Lines $lines -BundleSrc $OutFile -PlugName 'codexwasm-subject'
