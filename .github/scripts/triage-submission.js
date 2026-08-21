"use strict";

const CATEGORIES = [
  "finance",
  "ecommerce",
  "social-media",
  "developer-tools",
  "data",
  "productivity",
  "web3",
  "ai",
  "search",
  "other",
];

function field(body, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = String(body || "").match(
    new RegExp(`(?:^|\\n)### ${escaped}\\s*\\n([\\s\\S]*?)(?=\\n### |$)`),
  );
  const value = match ? match[1].trim() : "";
  return value === "_No response_" ? "" : value;
}

function parseSubmission(body) {
  const tagsRaw = field(body, "Tags");
  return {
    name: field(body, "Server name"),
    repoUrl: field(body, "GitHub repository URL"),
    description: field(body, "Description"),
    category: field(body, "Category"),
    tags: tagsRaw.split(",").map((tag) => tag.trim()).filter(Boolean),
    confirmed: /- \[[xX]\]\s+This is a real, publicly-accessible MCP server/.test(
      field(body, "Confirm"),
    ),
  };
}

function labelNames(issue) {
  return (issue.labels || []).map((label) =>
    typeof label === "string" ? label : label.name,
  );
}

function isSubmissionIssue(issue) {
  if (labelNames(issue).includes("server-submission")) return true;
  const body = String(issue.body || "");
  return (
    /^\[Server\]\s+/i.test(String(issue.title || "")) &&
    body.includes("### Server name") &&
    body.includes("### GitHub repository URL") &&
    body.includes("### Description")
  );
}

function canonicalGitHubRepo(rawUrl) {
  let parsed;
  try {
    parsed = new URL(String(rawUrl || "").trim());
  } catch {
    return null;
  }
  if (
    parsed.protocol !== "https:" ||
    parsed.hostname.toLowerCase() !== "github.com" ||
    parsed.search ||
    parsed.hash
  ) {
    return null;
  }
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (parts.length !== 2) return null;
  const owner = parts[0];
  const repo = parts[1].replace(/\.git$/i, "");
  if (!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/.test(owner)) return null;
  if (!/^[A-Za-z0-9_.-]+$/.test(repo)) return null;
  return {
    owner,
    repo,
    fullName: `${owner}/${repo}`,
    url: `https://github.com/${owner}/${repo}`,
  };
}

function validateSubmission(submission) {
  const errors = [];
  if (!submission.name) errors.push("Server name is required.");
  if (!submission.repoUrl) errors.push("GitHub repository URL is required.");
  if (!submission.description) errors.push("Description is required.");
  if (!submission.category) {
    errors.push("Category is required.");
  } else if (!CATEGORIES.includes(submission.category)) {
    errors.push(`Category must be one of: ${CATEGORIES.join(", ")}.`);
  }
  if (!submission.tags.length) errors.push("At least one tag is required.");
  if (!submission.confirmed) {
    errors.push("The public MCP server confirmation checkbox must be checked.");
  }
  if (submission.repoUrl && !canonicalGitHubRepo(submission.repoUrl)) {
    errors.push(
      "GitHub repository URL must look like `https://github.com/owner/repo`.",
    );
  }
  return errors;
}

function statusMarker(issueNumber) {
  return `<!-- mcp-radar-submission-status:${issueNumber} -->`;
}

function normalizeUrl(url) {
  return String(url || "").trim().replace(/\/+$/, "").toLowerCase();
}

async function ensureLabel(github, repo, name, color, description) {
  try {
    await github.rest.issues.getLabel({ ...repo, name });
  } catch (error) {
    if (error.status !== 404) throw error;
    await github.rest.issues.createLabel({
      ...repo,
      name,
      color,
      description,
    });
  }
}

async function setStatus(github, repo, issueNumber, body) {
  const marker = statusMarker(issueNumber);
  const comments = await github.paginate(github.rest.issues.listComments, {
    ...repo,
    issue_number: issueNumber,
    per_page: 100,
  });
  const prior = comments.find(
    (comment) =>
      comment.user?.type === "Bot" && String(comment.body || "").includes(marker),
  );
  const completeBody = `${marker}\n${body}`;
  if (prior) {
    await github.rest.issues.updateComment({
      ...repo,
      comment_id: prior.id,
      body: completeBody,
    });
  } else {
    await github.rest.issues.createComment({
      ...repo,
      issue_number: issueNumber,
      body: completeBody,
    });
  }
}

async function readJson(github, repo, path, ref, fallback) {
  try {
    const response = await github.rest.repos.getContent({ ...repo, path, ref });
    if (Array.isArray(response.data) || response.data.type !== "file") {
      throw new Error(`${path} is not a file`);
    }
    return {
      value: JSON.parse(Buffer.from(response.data.content, "base64").toString()),
      sha: response.data.sha,
    };
  } catch (error) {
    if (error.status === 404 && fallback !== undefined) {
      return { value: fallback, sha: null };
    }
    throw error;
  }
}

async function listOpenPulls(github, repo, base) {
  return github.paginate(github.rest.pulls.list, {
    ...repo,
    state: "open",
    base,
    per_page: 100,
  });
}

async function closeOpenSubmissionPulls(github, repo, base, issueNumber) {
  const branch = `submission/issue-${issueNumber}`;
  const repositoryName = `${repo.owner}/${repo.repo}`.toLowerCase();
  const pulls = await listOpenPulls(github, repo, base);
  const stalePulls = pulls.filter(
    (pull) =>
      pull.head.ref === branch &&
      String(pull.head.repo?.full_name || "").toLowerCase() === repositoryName,
  );
  await Promise.all(
    stalePulls.map((pull) =>
      github.rest.pulls.update({
        ...repo,
        pull_number: pull.number,
        state: "closed",
      }),
    ),
  );
}

async function findPendingDuplicate(
  github,
  repo,
  base,
  currentBranch,
  canonicalUrl,
) {
  const pulls = await listOpenPulls(github, repo, base);
  const repositoryName = `${repo.owner}/${repo.repo}`.toLowerCase();
  const submissionPulls = pulls.filter(
    (pull) =>
      String(pull.head.repo?.full_name || "").toLowerCase() === repositoryName &&
      pull.head.ref.startsWith("submission/issue-") &&
      pull.head.ref !== currentBranch,
  );
  for (const pull of submissionPulls) {
    const proposed = await readJson(
      github,
      repo,
      "data/supplemental_servers.json",
      pull.head.sha,
    );
    if (!Array.isArray(proposed.value)) {
      throw new Error(
        `data/supplemental_servers.json in PR #${pull.number} is not a list`,
      );
    }
    const server = proposed.value.find(
      (candidate) => normalizeUrl(candidate.url) === normalizeUrl(canonicalUrl),
    );
    if (server) return { pullNumber: pull.number, server };
  }
  return null;
}

async function run({ github, context, core }) {
  const issue = context.payload.issue;
  if (!issue || !isSubmissionIssue(issue)) {
    core.info("Issue is not a server submission; nothing to do.");
    return;
  }

  const repo = context.repo;
  const issueNumber = issue.number;
  const base = context.payload.repository?.default_branch || "main";
  const branch = `submission/issue-${issueNumber}`;

  await ensureLabel(
    github,
    repo,
    "server-submission",
    "0e8a16",
    "community MCP server submission via issue form",
  );
  if (!labelNames(issue).includes("server-submission")) {
    await github.rest.issues.addLabels({
      ...repo,
      issue_number: issueNumber,
      labels: ["server-submission"],
    });
  }

  const submission = parseSubmission(issue.body);
  const errors = validateSubmission(submission);
  const reject = async (messages) => {
    await closeOpenSubmissionPulls(github, repo, base, issueNumber);
    await ensureLabel(
      github,
      repo,
      "invalid",
      "d93f0b",
      "submission rejected by triage (bad URL, duplicate, or missing fields)",
    );
    await github.rest.issues.addLabels({
      ...repo,
      issue_number: issueNumber,
      labels: ["invalid"],
    });
    await setStatus(
      github,
      repo,
      issueNumber,
      `❌ Submission needs changes:\n\n${messages.map((message) => `- ${message}`).join("\n")}\n\nEdit the issue to run validation again.`,
    );
  };

  if (errors.length) {
    await reject(errors);
    return;
  }

  const submittedRepo = canonicalGitHubRepo(submission.repoUrl);
  let metadata;
  try {
    metadata = (
      await github.rest.repos.get({
        owner: submittedRepo.owner,
        repo: submittedRepo.repo,
      })
    ).data;
  } catch (error) {
    if (error.status === 404) {
      await reject(["The GitHub repository is not public or could not be found."]);
      return;
    }
    throw error;
  }
  if (metadata.private || metadata.disabled) {
    await reject(["The GitHub repository must be public and accessible."]);
    return;
  }

  const canonical = {
    owner: metadata.owner.login,
    repo: metadata.name,
    fullName: metadata.full_name,
    url: metadata.html_url,
  };
  const [generated, supplemental] = await Promise.all([
    readJson(github, repo, "data/servers.json", base, { servers: [] }),
    readJson(github, repo, "data/supplemental_servers.json", base, []),
  ]);
  if (!Array.isArray(generated.value.servers)) {
    throw new Error("data/servers.json has no servers list");
  }
  if (!Array.isArray(supplemental.value)) {
    throw new Error("data/supplemental_servers.json is not a list");
  }

  const existing = [...generated.value.servers, ...supplemental.value].find(
    (server) => normalizeUrl(server.url) === normalizeUrl(canonical.url),
  );
  if (existing) {
    await reject([
      `\`${canonical.fullName}\` is already in the directory (source: ${existing.source || "unknown"}).`,
    ]);
    return;
  }

  const pendingDuplicate = await findPendingDuplicate(
    github,
    repo,
    base,
    branch,
    canonical.url,
  );
  if (pendingDuplicate) {
    await reject([
      `\`${canonical.fullName}\` is already proposed by #${pendingDuplicate.pullNumber}.`,
    ]);
    return;
  }

  if (labelNames(issue).includes("invalid")) {
    await github.rest.issues.removeLabel({
      ...repo,
      issue_number: issueNumber,
      name: "invalid",
    }).catch((error) => {
      if (error.status !== 404) throw error;
    });
  }

  const entry = {
    name: submission.name,
    url: canonical.url,
    description: submission.description,
    category: submission.category,
    tags: submission.tags,
    stars: metadata.stargazers_count,
    last_updated: metadata.pushed_at || metadata.updated_at,
    source: "supplemental",
  };
  const updatedSupplemental = [...supplemental.value, entry];
  const baseRef = await github.rest.git.getRef({ ...repo, ref: `heads/${base}` });
  try {
    await github.rest.git.createRef({
      ...repo,
      ref: `refs/heads/${branch}`,
      sha: baseRef.data.object.sha,
    });
  } catch (error) {
    if (error.status !== 422) throw error;
    await github.rest.git.updateRef({
      ...repo,
      ref: `heads/${branch}`,
      sha: baseRef.data.object.sha,
      force: true,
    });
  }

  const branchFile = await readJson(
    github,
    repo,
    "data/supplemental_servers.json",
    branch,
    [],
  );
  await github.rest.repos.createOrUpdateFileContents({
    ...repo,
    path: "data/supplemental_servers.json",
    branch,
    content: Buffer.from(
      `${JSON.stringify(updatedSupplemental, null, 2)}\n`,
    ).toString("base64"),
    message: `submission: add ${submission.name} (issue #${issueNumber})`,
    ...(branchFile.sha ? { sha: branchFile.sha } : {}),
  });

  const title = `Add ${submission.name} (submission #${issueNumber})`;
  const prBody =
    `Automated submission from #${issueNumber} by @${issue.user.login}.\n\n` +
    `\`\`\`json\n${JSON.stringify(entry, null, 2)}\n\`\`\`\n\n` +
    `Review and merge to publish.\n\nCloses #${issueNumber}`;
  const openPulls = await github.rest.pulls.list({
    ...repo,
    state: "open",
    head: `${repo.owner}:${branch}`,
    base,
  });
  let pull;
  if (openPulls.data.length) {
    pull = openPulls.data[0];
    await github.rest.pulls.update({
      ...repo,
      pull_number: pull.number,
      title,
      body: prBody,
    });
  } else {
    pull = (
      await github.rest.pulls.create({
        ...repo,
        title,
        head: branch,
        base,
        body: prBody,
      })
    ).data;
  }

  await setStatus(
    github,
    repo,
    issueNumber,
    `✅ Validated \`${canonical.fullName}\` (stars: ${entry.stars}, last push: ${entry.last_updated}). Opened or updated #${pull.number} for maintainer review.`,
  );
}

module.exports = {
  CATEGORIES,
  canonicalGitHubRepo,
  closeOpenSubmissionPulls,
  findPendingDuplicate,
  isSubmissionIssue,
  parseSubmission,
  run,
  statusMarker,
  validateSubmission,
};
