import { spawnSync } from "node:child_process"
import { randomUUID } from "node:crypto"
import { existsSync, rmSync } from "node:fs"
import { mkdir, mkdtemp, open, readFile, rename, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { basename, dirname, join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript"

const frontendDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const repositoryDirectory = resolve(frontendDirectory, "..")
const backendDirectory = join(repositoryDirectory, "backend")
const generatedDirectory = join(frontendDirectory, "src", "api", "generated")
const generatedFile = join(generatedDirectory, "schema.ts")
const activeTemporaryFiles = new Set()
const realFilesystem = { open, rename, rm }

process.once("exit", () => {
  for (const temporaryFile of activeTemporaryFiles) {
    rmSync(temporaryFile, { force: true })
  }
})

function pythonCommand() {
  if (process.env.PYTHON) return process.env.PYTHON
  const virtualEnvironmentPython = process.platform === "win32"
    ? join(backendDirectory, ".venv", "Scripts", "python.exe")
    : join(backendDirectory, ".venv", "bin", "python")
  return existsSync(virtualEnvironmentPython) ? virtualEnvironmentPython : "python"
}

async function generatedContract() {
  const temporaryDirectory = await mkdtemp(join(tmpdir(), "sinofgear-openapi-"))
  const schemaFile = join(temporaryDirectory, "schema.json")
  try {
    const exported = spawnSync(
      pythonCommand(),
      [
        "manage.py", "spectacular", "--settings=config.test_settings", "--validate",
        "--format", "openapi-json", "--file", schemaFile,
      ],
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
    const openapi = await readFile(schemaFile, "utf8")
    JSON.parse(openapi)
    const nodes = await openapiTS(pathToFileURL(schemaFile), {
      alphabetize: true,
      immutable: true,
    })
    return [
      COMMENT_HEADER,
      astToString(nodes),
      "\nexport type RuntimeOpenAPIDocument = {\n",
      "    readonly paths: Record<string, Record<string, unknown>>;\n",
      "    readonly components: { readonly schemas: Record<string, unknown> };\n",
      "    readonly [key: string]: unknown;\n",
      "};\n",
      "export const openapiDocument = JSON.parse(",
      JSON.stringify(openapi.trim()),
      ") as RuntimeOpenAPIDocument;\n",
    ].join("")
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true })
  }
}

export async function writeFileAtomically(destination, contents, filesystem = realFilesystem) {
  await mkdir(dirname(destination), { recursive: true })
  const temporaryFile = join(
    dirname(destination),
    `.${basename(destination)}.${process.pid}.${randomUUID()}.tmp`,
  )
  activeTemporaryFiles.add(temporaryFile)
  let handle
  try {
    handle = await filesystem.open(temporaryFile, "wx", 0o600)
    await handle.writeFile(contents, "utf8")
    await handle.sync()
    await handle.close()
    handle = undefined
    await filesystem.rename(temporaryFile, destination)
  } finally {
    if (handle) await handle.close().catch(() => undefined)
    await filesystem.rm(temporaryFile, { force: true }).catch(() => undefined)
    activeTemporaryFiles.delete(temporaryFile)
  }
}

export async function main(mode = process.argv[2] ?? "generate", options = {}) {
  if (mode !== "generate" && mode !== "check") {
    throw new Error("Usage: node scripts/generate-api.mjs [generate|check]")
  }
  const targetFile = options.generatedFile ?? generatedFile
  const createContract = options.generatedContract ?? generatedContract
  const filesystem = options.filesystem ?? realFilesystem
  const expected = await createContract()
  if (mode === "check") {
    const current = await readFile(targetFile, "utf8").catch(() => null)
    if (current !== expected) {
      throw new Error("Generated API artifact is stale. Run `pnpm api:generate` and commit the result.")
    }
    process.stdout.write("Generated API artifact is current.\n")
    return
  }
  await writeFileAtomically(targetFile, expected, filesystem)
  process.stdout.write(`Generated ${targetFile}\n`)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
