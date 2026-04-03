#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { spawn } from "child_process";

const server = new McpServer({
  name: "debuggai",
  version: "0.1.0",
});

/**
 * Run the DebuggAI Python CLI and return the JSON result.
 */
function runDebuggAI(args: string[]): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  return new Promise((resolve) => {
    const proc = spawn("debuggai", [...args, "--format", "json"], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
    });
    proc.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
    });

    proc.on("close", (code) => {
      resolve({ stdout, stderr, exitCode: code ?? 1 });
    });

    proc.on("error", (err) => {
      resolve({ stdout: "", stderr: err.message, exitCode: 1 });
    });
  });
}

// Tool: scan_code
server.tool(
  "scan_code",
  "Scan code for AI-generated bugs, security issues, and performance problems",
  {
    target: z.string().optional().describe("File or directory to scan (defaults to current directory)"),
    diff: z.string().optional().describe("Git ref to diff against (e.g., HEAD~1)"),
    staged: z.boolean().optional().describe("Scan staged changes only"),
    no_llm: z.boolean().optional().describe("Skip LLM analysis for faster results"),
    strict: z.boolean().optional().describe("Use high strictness (report all severities)"),
  },
  async ({ target, diff, staged, no_llm, strict }) => {
    const args: string[] = ["scan"];
    if (target) args.push("--file", target);
    if (diff) args.push("--diff", diff);
    if (staged) args.push("--staged");
    if (no_llm) args.push("--no-llm");
    if (strict) args.push("--strict");

    const result = await runDebuggAI(args);

    try {
      const report = JSON.parse(result.stdout);
      const summary = report.summary;
      const issueCount = summary.total_issues;

      let text = `DebuggAI Scan Complete\n`;
      text += `Issues: ${summary.critical} critical, ${summary.major} major, ${summary.minor} minor, ${summary.info} info\n`;
      if (summary.scan_duration_ms) text += `Duration: ${summary.scan_duration_ms}ms\n`;
      text += `\n`;

      for (const issue of report.issues) {
        const loc = issue.location
          ? ` ${issue.location.file}${issue.location.line ? `:${issue.location.line}` : ""}`
          : "";
        text += `[${issue.severity.toUpperCase()}] [${issue.category.toUpperCase()}] ${issue.title}${loc}\n`;
        text += `  ${issue.description}\n`;
        if (issue.suggestion) text += `  Fix: ${issue.suggestion}\n`;
        text += `\n`;
      }

      if (issueCount === 0) text += "No issues found!\n";

      return { content: [{ type: "text" as const, text }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: result.stdout || result.stderr || "Scan failed" }],
        isError: true,
      };
    }
  }
);

// Tool: verify_intent
server.tool(
  "verify_intent",
  "Verify code matches a natural language intent. Returns Prompt Fidelity Score.",
  {
    intent: z.string().describe("The intent to verify (what the code should do)"),
    target: z.string().optional().describe("File or directory to verify against"),
    diff: z.string().optional().describe("Git ref to verify against"),
  },
  async ({ intent, target, diff }) => {
    const args: string[] = ["verify", "--intent", intent];
    if (target) args.push("--file", target);
    if (diff) args.push("--diff", diff);

    const result = await runDebuggAI(args);

    try {
      const report = JSON.parse(result.stdout);
      let text = `Intent Verification\n`;
      text += `Intent: "${intent}"\n`;

      if (report.intent) {
        text += `Prompt Fidelity Score: ${report.intent.fidelity_score}/100\n\n`;

        for (const r of report.intent.results || []) {
          const iconMap: Record<string, string> = { pass: "+", fail: "x", partial: "~", unknown: "?" };
          const icon = iconMap[r.status as string] || "?";
          text += `[${icon}] ${r.assertion.description}\n`;
          text += `  Expected: ${r.assertion.expect}\n`;
          if (r.evidence) text += `  Found: ${r.evidence}\n`;
          text += `\n`;
        }
      }

      if (report.issues?.length > 0) {
        text += `\nAdditional Issues Found: ${report.issues.length}\n`;
        for (const issue of report.issues) {
          text += `  [${issue.severity.toUpperCase()}] ${issue.title}\n`;
        }
      }

      return { content: [{ type: "text" as const, text }] };
    } catch {
      return {
        content: [{ type: "text" as const, text: result.stdout || result.stderr || "Verification failed" }],
        isError: true,
      };
    }
  }
);

// Tool: get_report
server.tool(
  "get_report",
  "Get a full DebuggAI report in JSON format for programmatic analysis",
  {
    target: z.string().optional().describe("File or directory to scan"),
    diff: z.string().optional().describe("Git ref to diff against"),
    no_llm: z.boolean().optional().describe("Skip LLM analysis"),
  },
  async ({ target, diff, no_llm }) => {
    const args: string[] = ["scan"];
    if (target) args.push("--file", target);
    if (diff) args.push("--diff", diff);
    if (no_llm) args.push("--no-llm");

    const result = await runDebuggAI(args);

    return {
      content: [{ type: "text" as const, text: result.stdout || result.stderr }],
      isError: result.exitCode > 0 && !result.stdout,
    };
  }
);

// Tool: configure
server.tool(
  "configure",
  "Show or initialize DebuggAI configuration for the current project",
  {
    action: z.enum(["show", "init"]).describe("Whether to show current config or initialize a new one"),
    directory: z.string().optional().describe("Project directory (defaults to cwd)"),
  },
  async ({ action, directory }) => {
    if (action === "init") {
      const args = ["init", directory || "."];
      const result = await runDebuggAI(args);
      return {
        content: [{ type: "text" as const, text: result.stdout || result.stderr }],
      };
    } else {
      const args = ["config"];
      const result = await runDebuggAI(args);
      return {
        content: [{ type: "text" as const, text: result.stdout || result.stderr }],
      };
    }
  }
);

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
