import assert from "node:assert/strict"
import { mkdtemp, mkdir, stat } from "node:fs/promises"
import { join } from "node:path"
import { tmpdir } from "node:os"
import { test } from "node:test"

import {
  assertOwnedRunRoot,
  buildE2EEnvironment,
  cleanupOwnedRun,
  removeOwnedRunRoot,
  RUN_MARKER,
  spawnOwnedChild,
} from "./launcher.mjs"

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

test("Playwright artifacts are confined to the owned run root", async () => {
  const runRoot = await mkdtemp(join(tmpdir(), RUN_MARKER))
  try {
    const environment = buildE2EEnvironment(runRoot, {
      apiOrigin: "http://127.0.0.1:40101",
      webOrigin: "http://127.0.0.1:40102",
      browser: "browser",
    })
    assert.equal(environment.PLAYWRIGHT_OUTPUT_DIR, join(runRoot, "playwright", "test-results"))
    assert.equal(environment.PLAYWRIGHT_REPORT_DIR, join(runRoot, "playwright", "report"))
  } finally {
    await removeOwnedRunRoot(runRoot)
  }
})

test("cleanup stops an owned child and grandchild before removing the run root", async () => {
  const runRoot = await mkdtemp(join(tmpdir(), RUN_MARKER))
  const grandchildProgram = [
    "process.on('SIGTERM',()=>{});",
    "setInterval(()=>{},1000);",
  ].join("")
  const parentProgram = [
    "const {spawn}=require('node:child_process');",
    `const child=spawn(process.execPath,['-e',${JSON.stringify(grandchildProgram)}],{stdio:'ignore'});`,
    "process.stdout.write(String(child.pid)+'\\n');",
    "process.on('SIGTERM',()=>setTimeout(()=>process.exit(0),50));",
    "setInterval(()=>{},1000);",
  ].join("")
  const parent = spawnOwnedChild(process.execPath, ["-e", parentProgram], {
    stdio: ["ignore", "pipe", "ignore"],
  })
  const grandchildPid = await new Promise((resolve, reject) => {
    let output = ""
    parent.stdout.setEncoding("utf8")
    parent.stdout.on("data", (chunk) => {
      output += chunk
      if (output.includes("\n")) resolve(Number(output.trim()))
    })
    parent.once("error", reject)
  })

  await cleanupOwnedRun({ children: [parent], runRoot })

  await assert.rejects(stat(runRoot), { code: "ENOENT" })
  assert.throws(() => process.kill(parent.pid, 0), { code: "ESRCH" })
  assert.throws(() => process.kill(grandchildPid, 0), { code: "ESRCH" })
})
