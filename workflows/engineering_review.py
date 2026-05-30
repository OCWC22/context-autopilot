export const meta = {
  name: 'engineering-review',
  description: 'Multi-subagent engineering review: 6 RLM-driven checks -> compact evidence -> deployment gate',
  phases: [
    { title: 'Checks', detail: '6 subagents (CI/CD, security, code quality, tests, deps, deploy) inspect via RLM, return compact evidence' },
    { title: 'Gate', detail: 'parent synthesizes a deployment-gate decision' },
  ],
}

// args: { repo: "<abs path>", sub_lm?: "mlx"|"claude" }
const REPO = (args && args.repo) || '.'
const SUB_LM = (args && args.sub_lm) || 'mlx'

// Each subagent externalizes its long context with an RLM at DEPTH=1 and returns
// only this small object. depth>=2 is banned (overthinks; latency explodes —
// RECEIPTS.md v2 / arXiv 2603.02615).
const EVIDENCE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    check: { type: 'string' },
    verdict: { type: 'string', enum: ['pass', 'warn', 'fail', 'unknown'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    summary: { type: 'string', description: '1-3 sentences, <= ~280 chars' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', enum: ['info', 'low', 'medium', 'high', 'critical'] },
          evidence_ref: { type: 'string', description: 'path:line or file#locator — a pointer, NOT the raw blob' },
          detail: { type: 'string', description: '<= ~200 chars' },
        },
        required: ['title', 'severity', 'evidence_ref', 'detail'],
      },
    },
    context_chars_seen: { type: 'number', description: 'approx raw chars the RLM externalized' },
    evidence_chars_returned: { type: 'number', description: 'approx chars in THIS object' },
    subcalls: { type: 'number', description: 'RLM sub-LM calls made (depth=1)' },
    notes: { type: 'array', items: { type: 'string' } },
  },
  required: ['check', 'verdict', 'confidence', 'summary', 'findings', 'context_chars_seen', 'evidence_chars_returned', 'subcalls'],
}

const SUBLM_NOTE = SUB_LM === 'mlx'
  ? `The RLM SUB-LM is the LOCAL MLX model on this Mac (OpenAI-compatible at http://127.0.0.1:8080/v1, served by mlx_lm.server). You (the subagent) are the PARENT/root that decides what to inspect; the cheap per-slice reading is delegated to the local model. Keep YOUR own token use tiny — never read whole files into your context; externalize them and sub-query.`
  : `Use your own reading for sub-calls (no local MLX endpoint configured).`

const RLM_INSTRUCTIONS = `
Use the RLM (Recursive Language Model) MCP to externalize long context. Load its tools first:
  ToolSearch select:mcp__rlm__rlm_init,mcp__rlm__rlm_add_buffer,mcp__rlm__rlm_grep,mcp__rlm__rlm_peek,mcp__rlm__rlm_chunk_indices,mcp__rlm__rlm_sub_query,mcp__rlm__rlm_sub_query_result,mcp__rlm__rlm_status
Then:
  1. rlm_init(session_id="check-<name>")
  2. rlm_add_buffer(<this check's files/logs/configs/traces under the repo>)   # context lives OUTSIDE your context window
  3. rlm_grep(<this check's patterns>)   # narrow BEFORE any sub-call
  4. rlm_peek(<top matches>)             # confirm structure
  5. rlm_sub_query(<your check question>, <chunk indices>)  # DEPTH=1 ONLY. ${SUBLM_NOTE}
  6. rlm_sub_query_result(...) -> stitch into the compact CheckEvidence below.
If the rlm MCP is unavailable, fall back to Grep/Read but STILL return only compact evidence — never dump raw files into your final answer.
HARD RULES: recursion depth = 1; cap sub-calls ~24; return pointers (path:line), not raw blobs; if a check's files don't exist, verdict="unknown".
`

const CHECKS = [
  { name: 'cicd', focus: 'CI/CD pipeline configs and build/CI logs', globs: '.github/workflows/*, .gitlab-ci.yml, ci/**, **/build.log', look: 'failures, broken/missing steps, missing dependency caching, flaky retries, nonzero exit codes' },
  { name: 'security', focus: 'source + scanner output + env/config', globs: '**/*.py, **/*.ts, **/*.env*, **/semgrep*.json, **/trivy*.json', look: 'hardcoded secrets/keys, injection (eval/exec/os.system/subprocess/SQL), disabled TLS verify, unsafe deserialization (pickle/yaml.load), named CVEs. Any high/critical => verdict fail' },
  { name: 'code_quality', focus: 'linter/type-checker output + source', globs: '**/eslint*.json, **/ruff*.txt, **/*lint*.log, **/mypy*.txt, **/*.py, **/*.ts', look: 'type errors, lint violations, dead/unused code, suppressed checks (ts-ignore/noqa/any), high complexity, TODO/FIXME/HACK' },
  { name: 'test_execution', focus: 'test runner output / JUnit XML / coverage', globs: '**/pytest*.log, **/junit*.xml, **/*test-results*.xml, **/coverage*.*', look: 'failing/erroring tests (names), skipped/xfail, coverage below ~80%. Any real failure => verdict fail' },
  { name: 'dependency_analysis', focus: 'manifests + lockfiles + audit output', globs: '**/package*.json, **/pnpm-lock.yaml, **/requirements*.txt, **/pyproject.toml, **/*audit*.json, **/Cargo.lock', look: 'known vulns (CVE/GHSA + severity), unpinned/wildcard versions, deprecated/suspicious packages' },
  { name: 'deployment_validation', focus: 'Dockerfiles, k8s/compose, IaC, deploy logs, Modal app', globs: '**/Dockerfile*, **/docker-compose*.yml, **/k8s/**, **/*.tf, **/modal_app.py, **/deploy*.log', look: ':latest tags, run-as-root/privileged, secrets in plaintext env, missing health checks / resource limits, 0.0.0.0 binds, failed/rollback events' },
]

phase('Checks')

const evidence = await parallel(
  CHECKS.map((c) => () =>
    agent(
      `You are the "${c.name}" engineering-check subagent reviewing the repository at:\n  ${REPO}\n\n` +
      `Your scope: ${c.focus}.\nFiles to inspect (globs, repo-relative): ${c.globs}\nLook specifically for: ${c.look}.\n\n` +
      RLM_INSTRUCTIONS +
      `\nReturn ONLY the CheckEvidence object. Set context_chars_seen to the approximate total size of what you externalized, evidence_chars_returned to the size of your returned object, and subcalls to how many RLM sub-queries you issued. Keep findings to the real, concrete ones (<= 20), each with a path:line evidence_ref.`,
      { label: c.name, phase: 'Checks', schema: EVIDENCE_SCHEMA }
    )
  )
)

phase('Gate')

const checks = evidence.filter(Boolean)
const sev = { info: 0, low: 1, medium: 2, high: 3, critical: 4 }
const anyFail = checks.some((e) => e.verdict === 'fail')
const hasCritical = checks.some((e) => (e.findings || []).some((f) => sev[f.severity] >= 3))
const anyWarn = checks.some((e) => e.verdict === 'warn')
const gate = anyFail || hasCritical ? 'fail' : anyWarn ? 'warn' : 'pass'

const totalContext = checks.reduce((s, e) => s + (e.context_chars_seen || 0), 0)
const totalEvidence = checks.reduce((s, e) => s + (e.evidence_chars_returned || 0), 0)

return {
  repo: REPO,
  sub_lm: SUB_LM,
  gate,
  checks: Object.fromEntries(checks.map((e) => [e.check, e.verdict])),
  total_findings: checks.reduce((s, e) => s + (e.findings || []).length, 0),
  context_externalized_chars: totalContext,
  evidence_returned_chars: totalEvidence,
  compression_ratio: totalEvidence ? Math.round((totalContext / totalEvidence) * 10) / 10 : 0,
  total_subcalls: checks.reduce((s, e) => s + (e.subcalls || 0), 0),
  evidence: checks,
}
