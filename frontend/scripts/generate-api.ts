import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript"

const frontendDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const repositoryDirectory = resolve(frontendDirectory, "..")
const backendDirectory = join(repositoryDirectory, "backend")
const generatedDirectory = join(frontendDirectory, "src", "api", "generated")
const generatedFile = join(generatedDirectory, "schema.ts")
const mode = process.argv[2] ?? "generate"

function pythonCommand(): string {
  if (process.env.PYTHON) return process.env.PYTHON
  const virtualEnvironmentPython = process.platform === "win32"
    ? join(backendDirectory, ".venv", "Scripts", "python.exe")
    : join(backendDirectory, ".venv", "bin", "python")
  return existsSync(virtualEnvironmentPython) ? virtualEnvironmentPython : "python"
}

async function generatedContract(): Promise<string> {
  const temporaryDirectory = await mkdtemp(join(tmpdir(), "sinofgear-openapi-"))
  const schemaFile = join(temporaryDirectory, "schema.yaml")
  try {
    const exported = spawnSync(
      pythonCommand(),
      ["manage.py", "spectacular", "--settings=config.test_settings", "--validate", "--file", schemaFile],
      {
        cwd: backendDirectory,
        encoding: "utf8",
        env: { ...process.env, PYTHONHASHSEED: "0" },
      },
    )
    if (exported.status !== 0) {
      process.stderr.write(exported.stdout)
      process.stderr.write(exported.stderr)
      throw new Error(`OpenAPI schema export failed with exit code ${exported.status ?? "unknown"}.`)
    }
    const nodes = await openapiTS(pathToFileURL(schemaFile), {
      alphabetize: true,
      immutable: true,
    })
    return `${COMMENT_HEADER}${astToString(nodes)}`
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true })
  }
}

async function main(): Promise<void> {
  if (mode !== "generate" && mode !== "check") {
    throw new Error("Usage: node scripts/generate-api.ts [generate|check]")
  }
  const expected = await generatedContract()
  if (mode === "check") {
    const current = await readFile(generatedFile, "utf8").catch(() => null)
    if (current !== expected) {
      throw new Error("Generated API types are stale. Run `pnpm api:generate` and commit the result.")
    }
    process.stdout.write("Generated API types are current.\n")
    return
  }
  await mkdir(generatedDirectory, { recursive: true })
  await writeFile(generatedFile, expected, "utf8")
  process.stdout.write(`Generated ${generatedFile}\n`)
}

await main()
