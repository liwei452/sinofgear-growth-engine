import { spawnSync } from "node:child_process"
import { resolve } from "node:path"
import { pathToFileURL } from "node:url"

import { describe, expect, it } from "vitest"


const script = resolve(process.cwd(), "scripts", "generate-api.mjs")


describe("API generator Node lifecycle", () => {
  it("runs without experimental TypeScript stripping", () => {
    const result = spawnSync(
      process.execPath,
      [
        "--no-experimental-strip-types",
        "--input-type=module",
        "--eval",
        `import(${JSON.stringify(pathToFileURL(script).href)}).then(module => console.log(typeof module.main))`,
      ],
      { encoding: "utf8" },
    )

    expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0)
    expect(result.stdout.trim()).toBe("function")
  })
})
