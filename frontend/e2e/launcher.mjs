import { spawn, spawnSync } from "node:child_process"
import { mkdtemp, rm } from "node:fs/promises"
import { createServer } from "node:net"
import { tmpdir } from "node:os"
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

export const RUN_MARKER = "sinofgear-phase-a-e2e-"
const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const repositoryDir = resolve(frontendDir, "..")
const backendDir = join(repositoryDir, "backend")

export function assertOwnedRunRoot(candidate, temporaryDirectory = tmpdir()) {
  const root = resolve(candidate)
  const temporaryRoot = resolve(temporaryDirectory)
  const fromTemporaryRoot = relative(temporaryRoot, root)
  if (
    !isAbsolute(root)
    || !basename(root).startsWith(RUN_MARKER)
    || fromTemporaryRoot.startsWith("..")
    || isAbsolute(fromTemporaryRoot)
    || root === temporaryRoot
  ) {
    throw new Error("Refusing to clean a directory that is not an owned Phase A E2E run root.")
  }
  return root
}

export async function removeOwnedRunRoot(candidate, temporaryDirectory = tmpdir()) {
  const root = assertOwnedRunRoot(candidate, temporaryDirectory)
  await rm(root, { recursive: true, force: true })
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

function pnpmInvocation(args) {
  const cli = process.env.npm_execpath
  if (!cli) throw new Error("The E2E launcher must be started by pnpm.")
  return { command: process.execPath, args: [cli, ...args] }
}

function run(command, args, options = {}) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: options.stdio ?? "inherit",
      windowsHide: true,
    })
    child.once("error", reject)
    child.once("exit", (code, signal) => {
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

function stopChild(child) {
  if (!child || child.exitCode !== null || !child.pid) return
  if (process.platform === "win32") {
    spawnSync("taskkill.exe", ["/pid", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    })
  } else {
    child.kill("SIGTERM")
  }
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
  const environment = {
    ...process.env,
    DJANGO_SETTINGS_MODULE: "config.e2e_settings",
    SINO_PHASE_A_E2E_ROOT: runRoot,
    SINO_PHASE_A_E2E_DB: join(runRoot, "phase-a.sqlite3"),
    SINO_PHASE_A_E2E_STORAGE: join(runRoot, "storage"),
    SINO_PHASE_A_E2E_WEB_ORIGIN: webOrigin,
    VITE_API_PROXY_TARGET: apiOrigin,
    PLAYWRIGHT_BASE_URL: webOrigin,
    PLAYWRIGHT_EXECUTABLE_PATH: browser,
  }
  const children = []
  const cleanup = async () => {
    for (const child of children.reverse()) stopChild(child)
    await removeOwnedRunRoot(runRoot)
  }
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.once(signal, () => { void cleanup().finally(() => process.exit(130)) })
  }
  try {
    await run(pythonExecutable(), ["manage.py", "migrate", "--noinput"], { cwd: backendDir, env: environment })
    await run(pythonExecutable(), ["manage.py", "seed_phase_a"], { cwd: backendDir, env: environment })
    const backend = spawn(
      pythonExecutable(),
      ["manage.py", "runserver", `127.0.0.1:${apiPort}`, "--noreload"],
      { cwd: backendDir, env: environment, stdio: "inherit", windowsHide: true },
    )
    children.push(backend)
    const vite = pnpmInvocation([
      "exec", "vite", "--host", "127.0.0.1", "--port", String(webPort), "--strictPort",
    ])
    const frontend = spawn(vite.command, vite.args, {
      cwd: frontendDir, env: environment, stdio: "inherit", windowsHide: true,
    })
    children.push(frontend)
    await Promise.all([
      waitFor(`${apiOrigin}/api/v1/auth/csrf`, backend, "Django"),
      waitFor(webOrigin, frontend, "Vite"),
    ])
    const playwright = pnpmInvocation([
      "exec", "playwright", "test", ...process.argv.slice(2),
    ])
    await run(playwright.command, playwright.args, { cwd: frontendDir, env: environment })
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
