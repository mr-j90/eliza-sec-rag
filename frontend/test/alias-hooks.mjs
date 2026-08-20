import { existsSync } from "node:fs";
import { dirname, join, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Teach Node the "@/" tsconfig path alias and TypeScript's extensionless
// imports, so `node --test` can load the app's modules unmodified. Next's
// bundler does this for the app itself; the test runner has no bundler.

const ROOT = resolvePath(dirname(fileURLToPath(import.meta.url)), "..");
const CANDIDATES = [".ts", ".tsx", ".js", ".mjs", "/index.ts", "/index.js"];

function withExtension(path) {
  if (existsSync(path)) return path;
  for (const suffix of CANDIDATES) {
    if (existsSync(path + suffix)) return path + suffix;
  }
  return path;
}

export function resolve(specifier, context, next) {
  if (specifier.startsWith("@/")) {
    const path = withExtension(join(ROOT, specifier.slice(2)));
    return next(pathToFileURL(path).href, context);
  }
  return next(specifier, context);
}
