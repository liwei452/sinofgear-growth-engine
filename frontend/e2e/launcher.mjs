import { spawn, spawnSync } from "node:child_process"
import { randomBytes } from "node:crypto"
import { existsSync, realpathSync } from "node:fs"
import { mkdir, mkdtemp, rm } from "node:fs/promises"
import { createServer } from "node:net"
import { tmpdir } from "node:os"
import { basename, dirname, isAbsolute, join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

export const RUN_MARKER = "sinofgear-phase-a-e2e-"
const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const repositoryDir = resolve(frontendDir, "..")
const backendDir = join(repositoryDir, "backend")

export function assertOwnedRunRoot(candidate, temporaryDirectory = tmpdir()) {
  if (!isAbsolute(candidate) || !existsSync(candidate)) {
    throw new Error("Refusing to clean a directory that is not an owned Phase A E2E run root.")
  }
  const root = realpathSync(candidate)
  const temporaryRoot = realpathSync(temporaryDirectory)
  if (
    !isAbsolute(root)
    || !basename(root).startsWith(RUN_MARKER)
    || dirname(root) !== temporaryRoot
    || root === temporaryRoot
  ) {
    throw new Error("Refusing to clean a directory that is not an owned Phase A E2E run root.")
  }
  return root
}

export async function removeOwnedRunRoot(candidate, temporaryDirectory = tmpdir()) {
  if (!existsSync(candidate)) return
  const root = assertOwnedRunRoot(candidate, temporaryDirectory)
  await rm(root, { recursive: true, force: true })
}

export function generateOwnershipSecret() {
  return randomBytes(32).toString("hex")
}

export function parseVisualAuditArguments(args, auditRoot) {
  if (args[0] !== "--visual-audit") return null
  if (args.length !== 2) throw new Error("Visual audit requires one bounded output directory.")
  const root = resolve(auditRoot)
  const auditDirectory = resolve(args[1])
  if (dirname(auditDirectory) !== root || !["initial", "confirmation"].includes(basename(auditDirectory))) {
    throw new Error("Visual audit output must be the initial or confirmation directory directly inside the SDD audit root.")
  }
  return {
    auditDirectory,
    playwrightArgs: ["business-outcome-navigation.spec.ts", "--grep", "visual audit"],
  }
}

export function buildE2EEnvironment(runRoot, { apiOrigin, webOrigin, browser, ownershipSecret }) {
  const root = assertOwnedRunRoot(runRoot)
  if (!/^[0-9a-f]{64}$/.test(ownershipSecret ?? "")) {
    throw new Error("A fresh 32-byte Phase A E2E ownership secret is required.")
  }
  return {
    ...process.env,
    DJANGO_SETTINGS_MODULE: "config.e2e_settings",
    SINO_PHASE_A_E2E_ROOT: root,
    SINO_PHASE_A_E2E_DB: join(root, "phase-a.sqlite3"),
    SINO_PHASE_A_E2E_STORAGE: join(root, "storage"),
    SINO_PHASE_A_E2E_OWNERSHIP_SECRET: ownershipSecret,
    SINO_PHASE_A_E2E_RUN_ID: root,
    SINO_PHASE_A_E2E_WEB_ORIGIN: webOrigin,
    VITE_API_PROXY_TARGET: apiOrigin,
    PLAYWRIGHT_BASE_URL: webOrigin,
    PLAYWRIGHT_EXECUTABLE_PATH: browser,
    PLAYWRIGHT_OUTPUT_DIR: join(root, "playwright", "test-results"),
    PLAYWRIGHT_REPORT_DIR: join(root, "playwright", "report"),
    PUBLIC_TRADE_PROVIDER_MODE: "FIXTURE",
  }
}

async function reservePort() {
  return await new Promise((resolvePort, reject) => {
    const server = createServer()
    server.once("error", reject)
    server.listen(0, "127.0.0.1", () => {
      const address = server.address()
      const port = typeof address === "object" && address ? address.port : 0
      server.close((error) => error ? reject(error) : resolvePort(port))
    })
  })
}

function pythonExecutable() {
  const windows = join(backendDir, ".venv", "Scripts", "python.exe")
  const unix = join(backendDir, ".venv", "bin", "python")
  if (process.platform === "win32") return windows
  return unix
}

function browserExecutable() {
  if (process.env.PLAYWRIGHT_EXECUTABLE_PATH) return process.env.PLAYWRIGHT_EXECUTABLE_PATH
  if (process.platform !== "win32") return ""
  const candidates = [
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ]
  return candidates.find((candidate) => {
    const result = spawnSync("powershell.exe", ["-NoProfile", "-Command", `Test-Path -LiteralPath '${candidate.replaceAll("'", "''")}'`], { encoding: "utf8", windowsHide: true })
    return result.status === 0 && result.stdout.trim().toLowerCase() === "true"
  }) ?? ""
}

function localNodeInvocation(entrypoint, args) {
  const script = join(frontendDir, "node_modules", ...entrypoint)
  if (!existsSync(script)) throw new Error(`Missing local E2E tool: ${script}`)
  return { command: process.execPath, args: [script, ...args] }
}

export function spawnOwnedChild(command, args, options = {}) {
  return spawn(command, args, {
    cwd: options.cwd,
    env: options.env,
    stdio: options.stdio ?? "inherit",
    windowsHide: true,
    detached: process.platform !== "win32",
  })
}

function run(command, args, options = {}) {
  return new Promise((resolveRun, reject) => {
    const child = spawnOwnedChild(command, args, options)
    options.children?.push(child)
    child.once("error", reject)
    child.once("exit", (code, signal) => {
      const index = options.children?.indexOf(child) ?? -1
      if (index >= 0) options.children.splice(index, 1)
      if (code === 0) resolveRun()
      else reject(new Error(`${command} exited with ${code ?? signal}`))
    })
  })
}

async function waitFor(url, child, label) {
  const deadline = Date.now() + 45_000
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${label} exited before becoming ready.`)
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Service is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 200))
  }
  throw new Error(`${label} did not become ready within 45 seconds.`)
}

function processGroupAlive(pid) {
  try {
    process.kill(-pid, 0)
    return true
  } catch (error) {
    if (error?.code === "ESRCH") return false
    throw error
  }
}

function waitForExit(child, timeoutMs) {
  if (!child || child.exitCode !== null) return Promise.resolve(true)
  return new Promise((resolveWait) => {
    const timeout = setTimeout(() => resolveWait(false), timeoutMs)
    child.once("exit", () => {
      clearTimeout(timeout)
      resolveWait(true)
    })
  })
}

async function waitForGroupExit(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (!processGroupAlive(pid)) return true
    await new Promise((resolveWait) => setTimeout(resolveWait, 25))
  }
  return !processGroupAlive(pid)
}

export async function stopOwnedChildTree(child) {
  if (!child || !child.pid) return
  if (process.platform === "win32") {
    if (child.exitCode === null) {
      spawnSync("taskkill.exe", ["/pid", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
      })
    }
    if (!(await waitForExit(child, 2_000))) {
      throw new Error(`Owned child tree ${child.pid} did not exit after taskkill.`)
    }
  } else {
    if (!processGroupAlive(child.pid)) return
    process.kill(-child.pid, "SIGTERM")
    if (!(await waitForGroupExit(child.pid, 1_000))) {
      process.kill(-child.pid, "SIGKILL")
      if (!(await waitForGroupExit(child.pid, 2_000))) {
        throw new Error(`Owned process group ${child.pid} survived SIGKILL.`)
      }
    }
    await waitForExit(child, 250)
  }
}

export async function cleanupOwnedRun({ children, runRoot }) {
  for (const child of [...children].reverse()) await stopOwnedChildTree(child)
  children.splice(0)
  if (!existsSync(runRoot)) return
  assertOwnedRunRoot(runRoot)
  await removeOwnedRunRoot(runRoot)
}

async function main() {
  const browser = browserExecutable()
  if (process.platform === "win32" && !browser) {
    throw new Error("No supported child-run browser was found for Playwright.")
  }
  const runRoot = assertOwnedRunRoot(await mkdtemp(join(tmpdir(), RUN_MARKER)))
  const apiPort = await reservePort()
  const webPort = await reservePort()
  const apiOrigin = `http://127.0.0.1:${apiPort}`
  const webOrigin = `http://127.0.0.1:${webPort}`
  const visualAudit = parseVisualAuditArguments(
    process.argv.slice(2),
    join(repositoryDir, ".superpowers", "sdd", "2026-08-20-business-outcome-navigation-ia", "visual-audit"),
  )
  if (visualAudit) await mkdir(visualAudit.auditDirectory, { recursive: true })
  const environment = {
    ...buildE2EEnvironment(runRoot, {
      apiOrigin,
      webOrigin,
      browser,
      ownershipSecret: generateOwnershipSecret(),
    }),
    ...(visualAudit ? { SINO_VISUAL_AUDIT_DIR: visualAudit.auditDirectory } : {}),
  }
  const children = []
  let cleanupPromise
  const cleanup = () => {
    cleanupPromise ??= cleanupOwnedRun({ children, runRoot })
    return cleanupPromise
  }
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.once(signal, () => { void cleanup().finally(() => process.exit(130)) })
  }
  try {
    await run(pythonExecutable(), ["manage.py", "migrate", "--noinput"], {
      cwd: backendDir, env: environment, children,
    })
    await run(pythonExecutable(), ["manage.py", "seed_phase_a"], {
      cwd: backendDir, env: environment, children,
    })
    const backend = spawnOwnedChild(
      pythonExecutable(),
      ["manage.py", "runserver", `127.0.0.1:${apiPort}`, "--noreload"],
      { cwd: backendDir, env: environment, stdio: "inherit", windowsHide: true },
    )
    children.push(backend)
    const vite = localNodeInvocation(
      ["vite", "bin", "vite.js"],
      ["--host", "127.0.0.1", "--port", String(webPort), "--strictPort"],
    )
    const frontend = spawnOwnedChild(vite.command, vite.args, {
      cwd: frontendDir, env: environment, stdio: "inherit", windowsHide: true,
    })
    children.push(frontend)
    await Promise.all([
      waitFor(`${apiOrigin}/api/v1/auth/csrf`, backend, "Django"),
      waitFor(webOrigin, frontend, "Vite"),
    ])
    const playwright = localNodeInvocation(
      ["@playwright", "test", "cli.js"],
      ["test", ...(visualAudit?.playwrightArgs ?? process.argv.slice(2))],
    )
    await run(playwright.command, playwright.args, {
      cwd: frontendDir, env: environment, children,
    })
  } finally {
    await cleanup()
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error)
    process.exitCode = 1
  })
}
