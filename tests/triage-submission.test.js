const test = require("node:test");
const assert = require("node:assert/strict");

const {
  parseSubmission,
  canonicalGitHubRepo,
  closeOpenSubmissionPulls,
  findPendingDuplicate,
  isSubmissionIssue,
  submissionFingerprint,
  validateSubmission,
  statusMarker,
} = require("../.github/scripts/triage-submission.js");

const completeBody = `### Server name

Agent QA

### GitHub repository URL

https://github.com/vostride/agent-qa.git/

### Description

Natural-language web and mobile application testing through MCP.

### Category

developer-tools

### Tags

testing, quality-assurance, browser-automation

### Confirm

- [x] This is a real, publicly-accessible MCP server with a GitHub repo.

### Disclosure

Affiliated with the official server.
`;

test("recognizes a complete submission even when GitHub omitted the label", () => {
  const issue = { title: "[Server] Agent QA", body: completeBody, labels: [] };
  assert.equal(isSubmissionIssue(issue), true);
});

test("recognizes a labeled submission even when its body is incomplete", () => {
  const issue = {
    title: "Any title",
    body: "Minimal body",
    labels: ["server-submission"],
  };
  assert.equal(isSubmissionIssue(issue), true);
});

test("does not treat an unrelated issue with a server-like title as a submission", () => {
  const issue = { title: "[Server] crashes on startup", body: "No issue-form fields", labels: [] };
  assert.equal(isSubmissionIssue(issue), false);
});

test("parses issue-form fields and ignores later optional sections", () => {
  const submission = parseSubmission(completeBody);
  assert.deepEqual(submission, {
    name: "Agent QA",
    repoUrl: "https://github.com/vostride/agent-qa.git/",
    description: "Natural-language web and mobile application testing through MCP.",
    category: "developer-tools",
    tags: ["testing", "quality-assurance", "browser-automation"],
    confirmed: true,
  });
});

test("canonicalizes GitHub repository URLs", () => {
  assert.deepEqual(canonicalGitHubRepo("https://github.com/Vostride/agent-qa.git/"), {
    owner: "Vostride",
    repo: "agent-qa",
    fullName: "Vostride/agent-qa",
    url: "https://github.com/Vostride/agent-qa",
  });
});

test("rejects repository URLs with extra paths or non-GitHub hosts", () => {
  assert.equal(canonicalGitHubRepo("https://github.com/a/b/issues"), null);
  assert.equal(canonicalGitHubRepo("https://example.com/a/b"), null);
});

test("validates required fields, categories, tags, and confirmation", () => {
  const valid = parseSubmission(completeBody);
  assert.deepEqual(validateSubmission(valid), []);

  assert.deepEqual(
    validateSubmission({ ...valid, category: "unknown", tags: [], confirmed: false }),
    [
      "Category must be one of: finance, ecommerce, social-media, developer-tools, data, productivity, web3, ai, search, other.",
      "At least one tag is required.",
      "The public MCP server confirmation checkbox must be checked.",
    ],
  );
});

test("fingerprint changes with the base list but ignores refreshed live metadata", () => {
  const entry = {
    name: "Agent QA",
    url: "https://github.com/vostride/agent-qa",
    description: "QA server",
    category: "developer-tools",
    tags: ["testing"],
    stars: 10,
    last_updated: "old",
    source: "supplemental",
  };
  const base = [{ name: "Existing", url: "https://github.com/a/b" }];
  assert.equal(
    submissionFingerprint(entry, base),
    submissionFingerprint({ ...entry, stars: 11, last_updated: "new" }, base),
  );
  assert.notEqual(
    submissionFingerprint(entry, base),
    submissionFingerprint(entry, [...base, { name: "New", url: "https://github.com/c/d" }]),
  );
});

test("uses a stable marker so reruns can update one status comment", () => {
  assert.equal(statusMarker(11), "<!-- mcp-radar-submission-status:11 -->");
});

test("closes a stale automation PR when revalidation rejects its issue", async () => {
  const updates = [];
  const github = {
    paginate: async () => [
      {
        number: 20,
        head: {
          ref: "submission/issue-11",
          repo: { full_name: "numbpill3d/mcp-radar" },
        },
      },
      {
        number: 99,
        head: {
          ref: "submission/issue-11",
          repo: { full_name: "attacker/fork" },
        },
      },
      {
        number: 21,
        head: {
          ref: "submission/issue-12",
          repo: { full_name: "numbpill3d/mcp-radar" },
        },
      },
    ],
    rest: {
      pulls: {
        list: Symbol("pulls.list"),
        update: async (args) => updates.push(args),
      },
    },
  };

  await closeOpenSubmissionPulls(github, { owner: "numbpill3d", repo: "mcp-radar" }, "main", 11);

  assert.deepEqual(updates, [
    {
      owner: "numbpill3d",
      repo: "mcp-radar",
      pull_number: 20,
      state: "closed",
    },
  ]);
});

test("finds duplicate repositories already proposed by another open submission PR", async () => {
  const encoded = Buffer.from(JSON.stringify([
    { name: "Agent QA", url: "https://github.com/vostride/agent-qa" },
  ])).toString("base64");
  const github = {
    paginate: async () => [
      {
        number: 98,
        head: {
          ref: "submission/issue-98",
          sha: "evil123",
          repo: { full_name: "attacker/fork" },
        },
      },
      {
        number: 22,
        head: {
          ref: "submission/issue-12",
          sha: "abc123",
          repo: { full_name: "numbpill3d/mcp-radar" },
        },
      },
      {
        number: 23,
        head: {
          ref: "feature/unrelated",
          sha: "def456",
          repo: { full_name: "numbpill3d/mcp-radar" },
        },
      },
    ],
    rest: {
      pulls: { list: Symbol("pulls.list") },
      repos: {
        getContent: async ({ ref }) => {
          assert.equal(ref, "abc123");
          return { data: { type: "file", content: encoded, sha: "filesha" } };
        },
      },
    },
  };

  const duplicate = await findPendingDuplicate(
    github,
    { owner: "numbpill3d", repo: "mcp-radar" },
    "main",
    "submission/issue-11",
    "https://github.com/Vostride/agent-qa/",
  );

  assert.deepEqual(duplicate, {
    pullNumber: 22,
    server: { name: "Agent QA", url: "https://github.com/vostride/agent-qa" },
  });
});
