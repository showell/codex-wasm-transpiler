// Assemble WAT into a module. wabt's own JS build, which is the same libwabt
// the wat2wasm binary is, so "the assembler accepted it" means what it means
// everywhere else -- and it means a lot here: the assembler is the only type
// checker the wasm emitter has, and it is what turns a whole class of emitter
// slip into a refused module rather than a wrong answer.
//
// TAIL CALLS ARE NOT OPTIONAL. The wasm plug emits `return_call` for a
// saturating self- or mutual tail call, which is how the compiler's own lexer
// cycle runs in constant stack; without the feature the assembler refuses the
// module outright.
//
//     node tools/wat2wasm.mjs <in.wat> <out.wasm>
import { readFileSync, writeFileSync } from 'node:fs';
import wabtInit from './node_modules/wabt/index.js';

const [, , watPath, wasmPath] = process.argv;
if (!watPath || !wasmPath) throw new Error('usage: wat2wasm.mjs <in.wat> <out.wasm>');
const wabt = await wabtInit();
const mod = wabt.parseWat(watPath, readFileSync(watPath, 'utf8'), { tail_call: true });
mod.resolveNames();
mod.validate();
writeFileSync(wasmPath, Buffer.from(mod.toBinary({}).buffer));
