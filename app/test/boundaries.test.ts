// Keeps the design honest: the core never reaches for a cloud library or an adapter, and the
// project adds no third-party runtime dependency without someone changing this test on purpose.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? sourceFiles(path) : path.endsWith(".ts") ? [path] : [];
  });
}

function importsOf(file: string): string[] {
  const text = readFileSync(file, "utf8");
  const found = [...text.matchAll(/(?:^|\n)\s*(?:import|export)\s[^;]*?from\s+["']([^"']+)["']/g)].map((m) => m[1]);
  found.push(...[...text.matchAll(/\bimport\(\s*["']([^"']+)["']\s*\)/g)].map((m) => m[1]));
  found.push(...[...text.matchAll(/(?:^|\n)\s*import\s+["']([^"']+)["']/g)].map((m) => m[1]));
  return found;
}

function inFolder(folder: string): string[] {
  return sourceFiles(join(SRC, folder));
}

function resolvedTarget(file: string, specifier: string): string {
  return relative(SRC, resolve(dirname(file), specifier));
}

describe("code boundaries", () => {
  it("finds the source files it is meant to check", () => {
    assert.ok(inFolder("domain").length > 0);
    assert.ok(inFolder("ports").length > 0);
    assert.ok(inFolder("adapters").length > 0);
  });

  it("domain imports nothing outside the domain folder, and no library at all", () => {
    for (const file of inFolder("domain")) {
      for (const specifier of importsOf(file)) {
        assert.ok(specifier.startsWith("."), `${relative(SRC, file)} imports ${specifier}`);
        assert.ok(resolvedTarget(file, specifier).startsWith("domain"), `${relative(SRC, file)} reaches outside the domain via ${specifier}`);
      }
    }
  });

  it("ports import only the domain and other ports, and no library", () => {
    for (const file of inFolder("ports")) {
      for (const specifier of importsOf(file)) {
        assert.ok(specifier.startsWith("."), `${relative(SRC, file)} imports ${specifier}`);
        const target = resolvedTarget(file, specifier);
        assert.ok(target.startsWith("domain") || target.startsWith("ports"), `${relative(SRC, file)} reaches into ${target}`);
      }
    }
  });

  it("only adapters touch the outside world, and only through Node's own modules", () => {
    for (const file of sourceFiles(SRC)) {
      for (const specifier of importsOf(file)) {
        if (specifier.startsWith(".")) continue;
        assert.ok(specifier.startsWith("node:"), `${relative(SRC, file)} imports third-party package ${specifier}`);
        const allowed = relative(SRC, file).startsWith("adapters");
        assert.ok(allowed, `${relative(SRC, file)} uses ${specifier}, which only adapters may do`);
      }
    }
  });

  it("no adapter imports another adapter's folder or the other way round", () => {
    for (const file of [...inFolder("domain"), ...inFolder("ports")]) {
      for (const specifier of importsOf(file)) {
        assert.ok(!resolvedTarget(file, specifier).startsWith("adapters"), `${relative(SRC, file)} imports an adapter`);
      }
    }
  });

  it("package.json declares no dependencies", () => {
    const manifest = JSON.parse(readFileSync(resolve(SRC, "../package.json"), "utf8"));
    for (const key of ["dependencies", "devDependencies", "optionalDependencies", "peerDependencies"]) {
      assert.equal(manifest[key], undefined, `${key} must stay empty until a dependency is discussed`);
    }
  });
});
