#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index < 0 ? fallback : process.argv[index + 1];
}

function pointer(document, path) {
  if (path === "") return document;
  return path.replace(/^\//, "").split("/").reduce((value, raw) => {
    const key = raw.replaceAll("~1", "/").replaceAll("~0", "~");
    return Array.isArray(value) ? value[Number(key)] : value[key];
  }, document);
}

function substitute(value, captures) {
  if (typeof value === "string" && value.startsWith("${") && value.endsWith("}")) {
    return captures[value.slice(2, -1)];
  }
  if (Array.isArray(value)) return value.map((item) => substitute(item, captures));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, substitute(item, captures)]));
  }
  return value;
}

function subset(expected, actual) {
  if (Array.isArray(expected)) {
    return Array.isArray(actual) && expected.length === actual.length
      && expected.every((item, index) => subset(item, actual[index]));
  }
  if (expected !== null && typeof expected === "object") {
    return actual !== null && typeof actual === "object"
      && Object.entries(expected).every(([key, item]) => key in actual && subset(item, actual[key]));
  }
  return Object.is(expected, actual);
}

async function request(baseUrl, token, step) {
  const spec = step.request;
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}${spec.path}`, {
    method: spec.method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(spec.json === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: spec.json === undefined ? undefined : JSON.stringify(spec.json),
    signal: AbortSignal.timeout((step.timeout_seconds ?? 10) * 1000),
  });
  return [response.status, await response.json()];
}

async function runPlan(plan, baseUrl, token, captures) {
  const results = [];
  for (const testCase of plan.cases) {
    const result = { id: testCase.id, passed: true, steps: [] };
    for (const rawStep of testCase.steps) {
      const step = substitute(rawStep, captures);
      const [status, response] = await request(baseUrl, token, step);
      const expected = step.expect;
      let passed = status === expected.status;
      if (expected.json !== undefined) passed = passed && subset(expected.json, response) && subset(response, expected.json);
      if (expected.json_subset !== undefined) passed = passed && subset(expected.json_subset, response);
      for (const [path, captureName] of Object.entries(step.capture ?? {})) {
        captures[captureName] = pointer(response, path);
      }
      for (const [path, captureName] of Object.entries(expected.equals_capture ?? {})) {
        passed = passed && Object.is(pointer(response, path), captures[captureName]);
      }
      result.steps.push({
        name: step.name ?? step.request.path, passed, status,
        ...(passed ? {} : { response }),
      });
      result.passed = result.passed && passed;
    }
    results.push(result);
  }
  return results;
}

const planPath = argument("--plan");
if (!planPath) throw new Error("--plan is required");
const baseUrl = argument("--base-url", "http://127.0.0.1:8741");
const tokenEnv = argument("--token-env", "ATLAS_COGNITIVE_TOKEN");
const token = process.env[tokenEnv];
if (!token) throw new Error(`missing bearer token environment variable: ${tokenEnv}`);
const capturesIn = argument("--captures-in");
const capturesOut = argument("--captures-out");
const captures = capturesIn ? JSON.parse(readFileSync(capturesIn, "utf8")) : {};
const plan = JSON.parse(readFileSync(planPath, "utf8"));
const results = await runPlan(plan, baseUrl, token, captures);
if (capturesOut) writeFileSync(capturesOut, JSON.stringify(captures));
results.forEach((result) => process.stdout.write(`${JSON.stringify(result)}\n`));
process.exitCode = results.every((result) => result.passed) ? 0 : 1;
