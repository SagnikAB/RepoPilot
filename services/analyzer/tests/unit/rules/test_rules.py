"""Positive and negative cases for every rule, through the real parse step."""

from __future__ import annotations

import pytest

from app.models.findings import Finding
from tests.helpers import extract


def _findings(code: str, path: str = "src/app.ts") -> list[Finding]:
    return extract(path, code).findings


def _hits(code: str, rule_id: str, path: str = "src/app.ts") -> list[tuple[int, str, str]]:
    """(start line, severity, evidence) of findings for one rule."""
    return [
        (f.location.start_line, f.severity.value, f.evidence)
        for f in _findings(code, path)
        if f.rule_id == rule_id
    ]


# -- js.dynamic-code-execution -------------------------------------------------------------

DYNAMIC = "js.dynamic-code-execution"


def test_dynamic_code_positive() -> None:
    code = """function run(input: string) {
  eval(input);
  window.eval("x" + input);
  new Function("a", input);
  Function(input)();
  setTimeout("tick(" + input + ")", 10);
  eval("1 + 1");
}
"""
    assert _hits(code, DYNAMIC) == [
        (2, "high", "eval(input);"),
        (3, "high", 'window.eval("x" + input);'),
        (4, "high", 'new Function("a", input);'),
        (5, "high", "Function(input)();"),
        (6, "high", 'setTimeout("tick(" + input + ")", 10);'),
        (7, "low", 'eval("1 + 1");'),  # constant code: reported, at low severity
    ]


def test_dynamic_code_negative() -> None:
    code = """function safe(cb: () => void, obj: { eval(x: string): void }) {
  setTimeout(cb, 10);
  setTimeout(() => cb(), 10);
  obj.eval("x");
  JSON.parse("{}");
  new Map();
  const evaluate = (x: string) => x;
  evaluate("1");
}
"""
    assert _hits(code, DYNAMIC) == []


# -- js.shell-command-construction ---------------------------------------------------------

SHELL = "js.shell-command-construction"


def test_shell_positive() -> None:
    code = """import { exec, execSync as run, spawn } from "child_process";
import * as cp from "node:child_process";
const legacy = require("child_process");
export function go(name: string, args: string[]) {
  exec(`git log ${name}`);
  run("ls " + name);
  cp.exec(name);
  legacy.execSync(name);
  require("child_process").exec(name);
  spawn(name, [], { shell: true });
  spawn("git", ["log", name], { shell: true });
}
"""
    assert [line for line, _, _ in _hits(code, SHELL)] == [5, 6, 7, 8, 9, 10, 11]


def test_shell_negative() -> None:
    code = """import { exec, spawn, execFile } from "child_process";
import { exec as runQuery } from "./db";
export function go(name: string, pattern: RegExp) {
  exec("git status");
  exec(`git status`);
  spawn("git", ["log", name]);
  execFile("git", ["log", name]);
  spawn(name, [], { shell: false });
  runQuery(name);
  pattern.exec(name);
  child.exec(name);
}
"""
    assert _hits(code, SHELL) == []


# -- js.sql-string-construction -------------------------------------------------------------

SQL = "js.sql-string-construction"


def test_sql_positive() -> None:
    code = """export function q(id: string, table: string) {
  const a = `SELECT * FROM users WHERE id = ${id}`;
  const b = "DELETE FROM sessions WHERE token = '" + id + "'";
  const c = 'UPDATE accounts SET balance = ' + id + ' WHERE id = 1';
  const d = `INSERT INTO ${table} (a) VALUES (1)`;
  const e = "select name from t where x = " + (id) + " and y = " + id;
}
"""
    assert [line for line, _, _ in _hits(code, SQL)] == [2, 3, 4, 5, 6]


def test_sql_negative() -> None:
    code = """export function q(id: string, n: number) {
  const constant = `SELECT * FROM users WHERE id = $1`;
  const plain = "SELECT * FROM users WHERE id = ?";
  const literalsOnly = "SELECT * FROM users " + "WHERE id = 1";
  const ui = `Selected ${n} items from your cart`;
  const settings = `update ${id} settings now`;
  const tagged = sql`SELECT * FROM users WHERE id = ${id}`;
  const math = n + 1;
  const greeting = "Hello " + id;
}
"""
    assert _hits(code, SQL) == []


def test_sql_concatenation_reports_one_finding_per_chain() -> None:
    hits = _hits('const s = "SELECT a FROM t WHERE x = " + a + " AND y = " + b + c;\n', SQL)

    assert len(hits) == 1


# -- js.tls-verification-disabled ------------------------------------------------------------

TLS = "js.tls-verification-disabled"


def test_tls_positive() -> None:
    code = """const agent = new https.Agent({ rejectUnauthorized: false });
const opts = { "strictSSL": false };
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
process.env["NODE_TLS_REJECT_UNAUTHORIZED"] = '0';
https.globalAgent.options.rejectUnauthorized = false;
"""
    assert [line for line, _, _ in _hits(code, TLS, "src/tls.js")] == [1, 2, 3, 4, 5]


def test_tls_negative() -> None:
    code = """const a = { rejectUnauthorized: true };
const b = { rejectUnauthorized: isDev };
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "1";
const c = { strict: false };
"""
    assert _hits(code, TLS, "src/tls.js") == []


# -- js.hardcoded-credential ------------------------------------------------------------------

CREDENTIAL = "js.hardcoded-credential"
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"  # AWS's documented example key ID
GITHUB_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def test_credentials_by_name_are_redacted() -> None:
    code = """const DB_PASSWORD = "hunter2-correct-horse";
const config = { apiKey: 'live-9f8e7d6c5b4a', clientSecret: "s3cr3t-value-123" };
class Auth { private signingKey = "k3y-material-xyz"; }
settings.authToken = "tok_1234567890ab";
"""
    hits = _hits(code, CREDENTIAL)

    assert [(line, severity) for line, severity, _ in hits] == [
        (1, "medium"),
        (2, "medium"),
        (2, "medium"),
        (3, "medium"),
        (4, "medium"),
    ]
    evidence = "\n".join(e for _, _, e in hits)
    for secret in ("hunter2", "live-9f8e", "s3cr3t", "k3y-material", "tok_1234"):
        assert secret not in evidence
    assert 'const DB_PASSWORD = "[REDACTED len=21]";' in evidence


def test_known_token_formats_are_high_severity_and_redacted() -> None:
    code = f'const AWS = "{AWS_KEY}";\nconst value = `{GITHUB_TOKEN}`;\nlog("{AWS_KEY}");\n'

    hits = _hits(code, CREDENTIAL)

    assert [(line, severity) for line, severity, _ in hits] == [
        (1, "high"),
        (2, "high"),
        (3, "high"),
    ]
    assert all(AWS_KEY not in e and GITHUB_TOKEN not in e for _, _, e in hits)
    assert len({f.id for f in _findings(code)}) == 3  # one finding per literal


def test_private_key_block_is_detected_and_redacted() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\\nMIIEowIBAAKCAQEA7\\n-----END RSA PRIVATE KEY-----"
    hits = _hits(f'export const key = "{pem}";\n', CREDENTIAL)

    assert len(hits) == 1 and hits[0][1] == "high"
    assert "MIIE" not in hits[0][2]


@pytest.mark.parametrize(
    "code",
    [
        'const passwordField = "user-password-input";',  # name does not end in a secret word
        'const tokenUrl = "https://example.com/oauth/token";',
        'const secretName = "prod/db/credentials";',
        'const PASSWORD = "";',
        'const password = "short";',  # below the minimum length
        'const password = "Enter your password";',  # whitespace: UI text
        'const password = "changeme";',
        'const apiKey = "xxxxxxxxxxxx";',
        'const token = "<your-token-here>";',
        "const secret = process.env.SECRET;",  # not a literal
        "const password = `${prefix}-123456789`;",  # interpolated, not constant
        'const publicKey = "MIIBIjANBgkqhkiG9w0BAQEF";',
        'const AKIA = "not-a-key";',
    ],
)
def test_credential_negatives(code: str) -> None:
    assert _hits(code + "\n", CREDENTIAL) == []


# -- cross-rule properties ---------------------------------------------------------------------


def test_findings_reference_the_file_and_valid_lines() -> None:
    code = "\n".join(
        [
            "// header",
            "export function run(q: string) {",
            "  eval(q);",
            "  return `SELECT * FROM t WHERE id = ${q}`;",
            "}",
            "",
        ]
    )
    result = extract("src/multi.ts", code)

    for finding in result.findings:
        assert finding.location.path == "src/multi.ts"
        assert 1 <= finding.location.start_line <= finding.location.end_line <= result.line_count
        assert finding.review_status.value == "needs_review"
        assert finding.next_step and finding.limitations and finding.cwe_id
    run_id = next(r.node.id for r in result.functions if r.node.name == "run")
    assert {f.function_id for f in result.findings} == {run_id}


def test_multiline_match_location_and_evidence() -> None:
    code = """const q = `
  SELECT *
  FROM users
  WHERE id = ${id}
  AND active = 1
  ORDER BY name
`;
"""
    [finding] = _findings(code)

    assert (finding.location.start_line, finding.location.end_line) == (1, 7)
    assert finding.evidence == "const q = `\nSELECT *\nFROM users\n..."
