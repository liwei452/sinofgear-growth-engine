import assert from "node:assert/strict"
import { mkdir, stat } from "node:fs/promises"
import { join } from "node:path"
import { test } from "node:test"

import { assertOwnedRunRoot, removeOwnedRunRoot, RUN_MARKER } from "./launcher.mjs"

test("cleanup accepts only marked child-owned temporary roots", async () => {
  const temporaryRoot = join(process.cwd(), ".tmp-launcher-test")
  const owned = join(temporaryRoot, `${RUN_MARKER}owned`)
  await mkdir(owned, { recursive: true })
  assert.equal(assertOwnedRunRoot(owned, temporaryRoot), owned)
  assert.throws(() => assertOwnedRunRoot(temporaryRoot, temporaryRoot), /Refusing/)
  assert.throws(() => assertOwnedRunRoot(join(temporaryRoot, "unmarked"), temporaryRoot), /Refusing/)
  assert.throws(() => assertOwnedRunRoot(join(temporaryRoot, "..", `${RUN_MARKER}outside`), temporaryRoot), /Refusing/)
  await removeOwnedRunRoot(owned, temporaryRoot)
  await assert.rejects(stat(owned), { code: "ENOENT" })
})
