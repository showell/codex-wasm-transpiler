// Run one of this project's wasm modules: source in on fd 0, the emitted
// module out, and a measurement of how much linear memory it took.
//
//     node tools/runwasm.mjs <module.wasm> <input> --out <wat> [--diag <txt>]
//
// THREE THINGS THIS DOES THAT `node:wasi` DOES NOT, each one paid for:
//
// 1. IT SURVIVES A LARGE LINEAR MEMORY. node:wasi aborts with SIGSEGV -- a
//    process abort, not a catchable trap -- once the module's memory grows
//    past roughly 40 MB, and the modules here reach thousands of times that.
//    The likely mechanism is a view cached across `memory.grow`, which
//    detaches the old buffer; every view below is re-derived after any call
//    that can allocate. safari-codex WASM_FINDINGS records the diagnosis and
//    names the twelve-line shim that works; this is that shim, grown up.
//
// 2. IT MEASURES. `CXWASM-MEM` on stderr is the whole point of the project's
//    first priority: wasm32 has a HARD 4 GiB ceiling and the compiler-sized
//    subject sits near it, so every run reports where it landed. The number
//    is exact rather than sampled -- the emitted prelude bump-allocates and
//    never frees, so final linear memory IS peak linear memory.
//
// 3. IT SPLITS THE STREAM. The wasm plug sends `print-text` and
//    `write-binary` both to fd 1, where the zig plug sends print-text to
//    stderr (zig's std.debug.print) and write-binary to stdout -- so the
//    native binary's report and module come out separated and this module's
//    do not. The split is by LINE and not by byte offset: the module's first
//    line is exactly `(module`, and no diagnostic line can be, because every
//    one of them starts `CDX` or `codexwasm:`. Recorded as a finding rather
//    than worked around silently -- FINDINGS.md item 1.
//
// The big stack is the bed's, not this project's: the emitted modules recurse
// once per list element, and the plug's own harness runs wasmtime at
// max-wasm-stack=16777216 for the same reason.
import { readFileSync, writeFileSync } from 'node:fs';
import { isMainThread, Worker, workerData } from 'node:worker_threads';

const MODULE_FIRST_LINE = '(module\n';

function parseArgs(argv) {
  const [wasm, input, ...rest] = argv;
  const opt = { wasm, input, out: null, diag: null, raw: false, memlog: null };
  for (let i = 0; i < rest.length; i++) {
    // --raw takes no value: a program that is not a compiler prints no
    // `(module` line, and splitting its output at one would report an empty
    // artifact for a run that worked perfectly. samples/ go through this.
    if (rest[i] === '--raw') { opt.raw = true; continue; }
    if (rest[i] === '--memlog') { opt.memlog = rest[++i]; continue; }
    if (rest[i] === '--out') opt.out = rest[++i];
    else if (rest[i] === '--diag') opt.diag = rest[++i];
    else throw new Error(`unknown argument ${rest[i]}`);
  }
  if (!opt.wasm || !opt.input || !opt.out) {
    throw new Error('usage: runwasm.mjs <module.wasm> <input> --out <wat> [--diag <txt>]');
  }
  return opt;
}

if (isMainThread) {
  const opt = parseArgs(process.argv.slice(2));
  const w = new Worker(new URL(import.meta.url), {
    workerData: opt,
    resourceLimits: { stackSizeMb: Number(process.env.CXWASM_STACK_MB || 256) },
  });
  w.on('exit', code => { process.exitCode = code; });
} else {
  const opt = workerData;
  const input = readFileSync(opt.input);
  let inPos = 0;

  let memory = null;
  // Views are cached and re-derived whenever the buffer is replaced, which is
  // what `memory.grow` does. Checking byteLength is cheaper than rebuilding
  // two views per call, and there are millions of calls.
  let bytes = null, view = null, seen = -1;
  // EVERY GROW THIS SEES IS A FREE SAMPLE. The views have to be rebuilt when
  // the buffer is replaced anyway, so noticing that costs nothing -- and a
  // module whose allocator only ever grows gives (time, size) pairs that are
  // an allocation profile. It samples only at host calls, so the front end,
  // which does no I/O between reading its input and reporting, appears as one
  // gap; that gap's END is the boundary this project most wants, because the
  // driver writes its diagnostics immediately before it emits.
  const grows = [];
  const refresh = () => {
    if (memory.buffer.byteLength !== seen) {
      seen = memory.buffer.byteLength;
      bytes = new Uint8Array(memory.buffer);
      view = new DataView(memory.buffer);
      if (opt.memlog) grows.push([Date.now() - started, seen]);
    }
  };

  // fd 1 is collected rather than streamed. The whole artifact is a few
  // megabytes, it has to be split before it can be written anywhere, and
  // writeSync per call cost more than everything else in the run put together.
  const stdout = [];
  const stderr = [];

  let firstWrite = null;
  const fd_write = (fd, iovs, n, nwritten) => {
    refresh();
    if (firstWrite === null) firstWrite = [Date.now() - started, memory.buffer.byteLength];
    let total = 0;
    for (let i = 0; i < n; i++) {
      const p = view.getUint32(iovs + i * 8, true);
      const len = view.getUint32(iovs + i * 8 + 4, true);
      if (len > 0) (fd === 1 ? stdout : stderr).push(Buffer.from(bytes.subarray(p, p + len)));
      total += len;
    }
    view.setUint32(nwritten, total, true);
    return 0;
  };

  const fd_read = (fd, iovs, n, nread) => {
    refresh();
    let total = 0;
    for (let i = 0; i < n; i++) {
      const p = view.getUint32(iovs + i * 8, true);
      const len = view.getUint32(iovs + i * 8 + 4, true);
      const take = Math.min(len, input.length - inPos);
      if (take > 0) {
        bytes.set(input.subarray(inPos, inPos + take), p);
        inPos += take;
        total += take;
      }
    }
    view.setUint32(nread, total, true);
    return 0;
  };

  let started = Date.now();
  const instance = new WebAssembly.Instance(
    new WebAssembly.Module(readFileSync(opt.wasm)),
    { wasi_snapshot_preview1: { fd_write, fd_read } });
  memory = instance.exports.memory;

  let trapped = null;
  try {
    instance.exports._start();
  } catch (err) {
    trapped = err;
  }

  const out = Buffer.concat(stdout);
  const cut = opt.raw ? 0 : out.indexOf(Buffer.from(MODULE_FIRST_LINE)) === 0
    ? 0
    : out.indexOf(Buffer.from('\n' + MODULE_FIRST_LINE));
  const [diag, module_] = opt.raw ? [Buffer.alloc(0), out] : cut < 0
    ? [out, Buffer.alloc(0)]                  // no module: a halt, or a trap
    : [out.subarray(0, cut === 0 ? 0 : cut + 1), out.subarray(cut === 0 ? 0 : cut + 1)];

  writeFileSync(opt.out, module_);
  if (opt.diag) writeFileSync(opt.diag, diag);
  if (stderr.length) process.stderr.write(Buffer.concat(stderr));

  const mb = memory.buffer.byteLength / (1024 * 1024);
  process.stderr.write(
    `CXWASM-MEM bytes=${memory.buffer.byteLength} mb=${mb.toFixed(1)} ` +
    `ceiling_pct=${(100 * memory.buffer.byteLength / 4294967296).toFixed(1)} ` +
    `seconds=${((Date.now() - started) / 1000).toFixed(1)} ` +
    `read=${inPos} wrote=${out.length}` +
    (firstWrite ? ` frontend_s=${(firstWrite[0] / 1000).toFixed(1)} frontend_mb=${(firstWrite[1] / 1048576).toFixed(1)}` : '') +
    `\n`);
  if (opt.memlog) {
    writeFileSync(opt.memlog,
      'ms,bytes\n' + grows.map(([m, b]) => `${m},${b}`).join('\n') + '\n');
  }

  if (trapped) {
    process.stderr.write(`CXWASM-TRAP ${trapped}\n`);
    process.exitCode = 3;
  } else if (module_.length === 0 && !opt.raw) {
    process.stderr.write('CXWASM-NO-MODULE: fd 1 carried no `(module` line\n');
    process.exitCode = 4;
  }
}
