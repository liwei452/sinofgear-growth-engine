import { open, readFile, readdir, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { mkdtemp, rm } from "node:fs/promises"

import { afterEach, describe, expect, it } from "vitest"

import { writeFileAtomically } from "./generate-api.mjs"


const temporaryDirectories = []

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map(directory =>
    rm(directory, { recursive: true, force: true }),
  ))
})

describe("atomic generated-artifact replacement", () => {
  it("preserves the canonical file and removes its temporary sibling after a partial write failure", async () => {
    const directory = await mkdtemp(join(tmpdir(), "sinofgear-atomic-test-"))
    temporaryDirectories.push(directory)
    const canonical = join(directory, "schema.ts")
    await writeFile(canonical, "canonical-contract", "utf8")
    const failingFilesystem = {
      open: async (...args) => {
        const handle = await open(...args)
        return {
          writeFile: async () => {
            await handle.writeFile("partial-new-contract", "utf8")
            throw new Error("simulated disk failure")
          },
          sync: () => handle.sync(),
          close: () => handle.close(),
        }
      },
      rename: async () => {
        throw new Error("rename must not run after a failed write")
      },
      rm,
    }

    await expect(writeFileAtomically(
      canonical,
      "replacement-contract",
      failingFilesystem,
    )).rejects.toThrow("simulated disk failure")

    expect(await readFile(canonical, "utf8")).toBe("canonical-contract")
    expect(await readdir(directory)).toEqual(["schema.ts"])
  })
})
