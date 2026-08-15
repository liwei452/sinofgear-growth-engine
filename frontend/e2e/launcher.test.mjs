import assert from "node:assert/strict"
import { mkdtemp, mkdir, stat } from "node:fs/promises"
import { join } from "node:path"
import { tmpdir } from "node:os"
import { test } from "node:test"

import {
  assertOwnedRunRoot,
  buildE2EEnvironment,
  cleanupOwnedRun,
  generateOwnershipSecret,
  removeOwnedRunRoot,
  RUN_MARKER,
  spawnOwnedChild,
  stopOwnedChildTree,
} from "./launcher.mjs"

test("cleanup accepts only marked child-owned temporary roots", async () => {
  const temporaryRoot = join(process.cwd(), ".tmp-launcher-test")
  const owned = join(temporaryRoot, `${RUN_MARKER}owned`)
  await mkdir(owned, { recursive: true })
  assert.equal(assertOwnedRunRoot(owned, temporaryRoot), owned)
  assert.throws(() => assertOwnedRunRoot(temporaryRoot, temporaryRoot), /Refusing/)
  assert.throws(() => assertOwnedRunRoot(join(temporaryRoot, "unmarked"), temporaryRoot), /Refusing/)
  assert.throws(() => assertOwnedRunRoot(join(temporaryRoot, "..", `${RUN_MARKER}outside`), temporaryRoot), /Refusing/)
  const nestedParent = join(temporaryRoot, "nested")
  const nestedMarked = join(nestedParent, `${RUN_MARKER}grandchild`)
  await mkdir(nestedMarked, { recursive: true })
  assert.throws(() => assertOwnedRunRoot(nestedMarked, temporaryRoot), /Refusing/)
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
      ownershipSecret: "a".repeat(64),
    })
    assert.equal(environment.PLAYWRIGHT_OUTPUT_DIR, join(runRoot, "playwright", "test-results"))
    assert.equal(environment.PLAYWRIGHT_REPORT_DIR, join(runRoot, "playwright", "report"))
    assert.equal(environment.SINO_PHASE_A_E2E_OWNERSHIP_SECRET, "a".repeat(64))
    assert.equal(environment.SINO_PHASE_A_E2E_RUN_ID, runRoot)
    assert.equal(environment.PUBLIC_TRADE_PROVIDER_MODE, "FIXTURE")
  } finally {
    await removeOwnedRunRoot(runRoot)
  }
})

test("ownership secrets are high-entropy per-run values", () => {
  const first = generateOwnershipSecret()
  const second = generateOwnershipSecret()
  assert.match(first, /^[0-9a-f]{64}$/)
  assert.notEqual(first, second)
})

test("cleanup stops children even when the marked run root is already missing", async () => {
  const missingRoot = join(tmpdir(), `${RUN_MARKER}missing-${process.pid}-${Date.now()}`)
  const child = spawnOwnedChild(process.execPath, ["-e", "setInterval(()=>{},1000)"], {
    stdio: "ignore",
  })
  try {
    await cleanupOwnedRun({ children: [child], runRoot: missingRoot })
    assert.throws(() => process.kill(child.pid, 0), { code: "ESRCH" })
  } finally {
    await stopOwnedChildTree(child)
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
