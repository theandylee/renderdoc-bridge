#!/usr/bin/env node
// Minimal client for the renderdoc-bridge extension (localhost HTTP API).
// Usage: node rdc.js [--port N] [--token T] status|reports|report <name> [paramsJson]|exec [file]|shutdown
//   report params: JSON object, e.g. '{"depth":2}' (quote as your shell requires)
//   exec: reads code from <file>, or from stdin when no file is given
// Prints the raw JSON response.
const fs = require("fs");

const raw = process.argv.slice(2);
let port = "38921";
let token = "renderdoc-bridge";
const args = [];
for (let i = 0; i < raw.length; i++) {
  if (raw[i] === "--port" && i + 1 < raw.length) { port = raw[++i]; }
  else if (raw[i] === "--token" && i + 1 < raw.length) { token = raw[++i]; }
  else { args.push(raw[i]); }
}

function usage() {
  console.error("usage: node rdc.js [--port N] [--token T] status|reports|report <name> [paramsJson]|exec [file]|shutdown");
  process.exit(1);
}

async function main() {
  const cmd = args.shift();
  const base = "http://127.0.0.1:" + port;
  const auth = "token=" + encodeURIComponent(token);
  let url;
  let opts;
  if (cmd === "status" || cmd === "reports" || cmd === "shutdown") {
    url = base + "/" + cmd + "?" + auth;
  } else if (cmd === "report") {
    const name = args.shift();
    if (!name) usage();
    const params = args.shift() || "{}";
    JSON.parse(params);
    url = base + "/report/" + name + "?" + auth + "&params=" + encodeURIComponent(params);
  } else if (cmd === "exec") {
    const file = args.shift();
    const code = file ? fs.readFileSync(file, "utf8") : fs.readFileSync(0, "utf8");
    url = base + "/exec?" + auth;
    opts = {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: code})};
  } else {
    usage();
  }
  const res = await fetch(url, opts);
  console.log(await res.text());
}

main().catch((e) => { console.error("rdc: " + e.message); process.exit(1); });
