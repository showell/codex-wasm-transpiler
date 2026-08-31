// Assemble every emitted module in one process. wat2wasm IS the wasm plug's
// type checker: a builtin the emitter has no arm for does not come out as a
// bad call, it comes out as a call_indirect against a type nothing declared,
// and only the assembler sees that.
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import wabtInit from './node_modules/wabt/index.js';
const dir = process.argv[2];
const wabt = await wabtInit();
const fails = [];
let ok = 0;
const only = JSON.parse(readFileSync(`${dir}/names.json`, 'utf8'));
for (const name of only) {
  const f = `${name}.wat`;
  try {
    const m = wabt.parseWat(f, readFileSync(`${dir}/${f}`, 'utf8'), { tail_call: true });
    m.resolveNames(); m.validate();
    // The binary is written, not just produced: stage 3 runs these.
    writeFileSync(`${dir}/${name}.wasm`, Buffer.from(m.toBinary({}).buffer));
    m.destroy?.();
    ok++;
  } catch (e) {
    fails.push([name, String(e.message || e).split('\n').slice(0, 3).join(' | ').slice(0, 220)]);
  }
}
console.log(`assembled ok: ${ok}   REFUSED: ${fails.length}`);
for (const [n, e] of fails) console.log(`  ${n}\n      ${e}`);
writeFileSync(`${dir}/asm-fails.json`, JSON.stringify(fails, null, 1));
