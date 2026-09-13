import { readFile } from "node:fs/promises";
import vm from "node:vm";

// Execute a server module with its framework and network edges supplied by the test.
export async function loadServerModule(path, globals, imports) {
  const context = vm.createContext({ URL, Headers, AbortSignal, ...globals });
  const module = new vm.SourceTextModule(await readFile(new URL(path, import.meta.url), "utf8"), {
    context,
  });
  await module.link((name) => {
    const values = imports[name];
    return new vm.SyntheticModule(Object.keys(values), function () {
      for (const [key, value] of Object.entries(values)) this.setExport(key, value);
    }, { context });
  });
  await module.evaluate();
  return module.namespace;
}
