# The transpiler subject: the hosted compiler's chapter set, plus the WASM
# emitter, plus the IR text parser, behind CodexWasmHarness.
#
# THIS LIST IS A DELIBERATE COPY and the drift is accepted. Upstream reaches
# the same set through three nested bundlers, and codex-zig-transpiler holds a
# flat copy of it for the zig emitter; this is that flat copy with one chapter
# swapped. Calling either sibling's bundler would couple this repository's
# subject -- the thing every byte of the fixed point is about -- to a file two
# projects away that moves for reasons of its own. A copy that breaks loudly at
# the next Update is the cheaper failure.
#
# EXACTLY ONE CHAPTER DIFFERS from codex-zig-transpiler's list:
# codex/plugs/wasm/WasmEmitter.codex where that one names
# codex/plugs/zig/ZigEmitter.codex. Everything else, including the X86_64
# chapters, is carried for the reasons that file's header gives, and those
# reasons are not restated here -- read it there. Keeping the two lists
# comparable line for line is what makes `diff` the drift check.
#
# Add-PlugChapter, Resolve-PlugForewords and Bundle-PlugSource come from the
# CHECKOUT's own plug-build-lib.ps1. Bundling resolves foreword cites and
# assembles quires by upstream's rules, and a reimplementation here would be a
# fork that drifts silently -- which is a different thing from the copy above,
# because a chapter LIST breaks loudly and a bundling RULE does not.
#
# IRTextParser IS carried, and that is load-bearing rather than incidental:
# the harness emits IR text and parses it straight back, because the wire
# DERIVES what the AST does not carry. CodexWasmHarness.codex has the argument.

param([string]$OutFile, [string]$Harness)
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
foreach ($ch in @('codex/compiler/Core/OffsetTable.codex',
                  'codex/compiler/Core/VmProfile.codex',
                  'codex/compiler/Types/Builtins.codex',
                  'codex/compiler/IR/Lir.codex',
                  'codex/compiler/Emit/EmitAllocator.codex',
                  'codex/compiler/Emit/CdxWriter.codex',
                  'codex/compiler/Emit/X86_64Boot.codex',
                  'codex/compiler/Emit/X86_64Encoder.codex',
                  'codex/compiler/Emit/X86_64State.codex',
                  'codex/compiler/Emit/X86_64.codex',
                  'codex/compiler/Emit/X86_64Builtins.codex',
                  'codex/compiler/Emit/X86_64Chapter.codex',
                  'codex/compiler/Emit/X86_64Compound.codex',
                  'codex/compiler/Emit/X86_64Helpers.codex',
                  'codex/compiler/Emit/X86_64IO.codex',
                  'codex/compiler/Emit/X86_64IPCHelpers.codex',
                  'codex/compiler/Emit/X86_64InsnCount.codex',
                  'codex/compiler/Emit/X86_64Lir.codex',
                  'codex/compiler/Emit/X86_64ListHelpers.codex',
                  'codex/compiler/Emit/X86_64ProcessHelpers.codex',
                  'codex/compiler/Emit/X86_64TextHelpers.codex',
                  'codex/compiler/Core/BuildSettings.codex',
                  'codex/compiler/Core/Phase.codex',
                  'codex/compiler/Core/PhaseAllocator.codex',
                  'codex/compiler/Core/TextFormat.codex',
                  'codex/compiler/Core/CdxCodes.codex',
                  'codex/compiler/Core/Severity.codex',
                  'codex/compiler/Core/SourceText.codex',
                  'codex/compiler/Core/Name.codex',
                  'codex/compiler/Core/Diagnostic.codex',
                  'codex/compiler/Core/DiagnosticBag.codex',
                  'codex/compiler/Core/Collections.codex',
                  'codex/compiler/Types/CodexType.codex',
                  'codex/compiler/Types/CodexTypeHelpers.codex',
                  'codex/compiler/IR/IRChapter.codex',
                  'codex/compiler/Syntax/Token.codex',
                  'codex/compiler/Syntax/Lexer.codex',
                  'codex/compiler/Syntax/SyntaxNodes.codex',
                  'codex/compiler/Syntax/ParserCore.codex',
                  'codex/compiler/Syntax/ParserExpressions.codex',
                  'codex/compiler/Syntax/Parser.codex',
                  'codex/compiler/Ast/AstNodes.codex',
                  'codex/compiler/Ast/Desugarer.codex',
                  'codex/compiler/Core/SkipListText.codex',
                  'codex/compiler/Semantics/ChapterScoper.codex',
                  'codex/compiler/Semantics/NameResolver.codex',
                  'codex/compiler/Types/CodexTypeTree.codex',
                  'codex/compiler/Types/TypeEnv.codex',
                  'codex/compiler/Types/Unifier.codex',
                  'codex/compiler/Types/TypeChecker.codex',
                  'codex/compiler/Types/TypeCheckerInference.codex',
                  'codex/compiler/IR/LoweringTypes.codex',
                  'codex/compiler/IR/Lowering.codex',
                  'codex/compiler/IR/ResolveTypes.codex',
                  'codex/compiler/Emit/IRTextEmitter.codex',
                  'codex/compiler/IR/Occurrence.codex',
                  'codex/compiler/IR/IRCheck.codex',
                  'codex/compiler/IR/LambdaLifting.codex',
                  'codex/compiler/IR/Simplify.codex',
                  'codex/compiler/IR/Passes.codex',
                  'codex/compiler/IR/LirTargets.codex',
                  'codex/compiler/Emit/CodexEmitter.codex',
                  'codex/plugs/common/IRTextParser.codex',
                  'codex/plugs/wasm/WasmEmitter.codex')) {
    Add-PlugChapter -Lines $lines -Path (Join-Path $repo $ch) -Quire 'Parsmi'
}

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
