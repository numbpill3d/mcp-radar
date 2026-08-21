# mcp radar

a small github pages site that publishes an auto-updating `servers.json`.

- site: github pages (static)
- data: regenerated daily by github actions

## what it is

- a directory you can browse
- a json endpoint other people can consume

## data sources

- best-of mcp servers: https://github.com/tolkonepiu/best-of-mcp-servers
- (optional enrichment) mcp servers hub: https://github.com/apappascs/mcp-servers-hub

## how to publish

1. create a new github repo (suggested: `mcp-radar`)
2. push this folder to the repo
3. enable github pages:
   - settings -> pages -> build and deployment
   - source: deploy from a branch
   - branch: `main` / root
4. wait for the scheduled action to generate `data/servers.json`

## how it updates

- workflow: `.github/workflows/update.yml`
- script: `scripts/update_data.py`

## local dev

open `index.html` in a browser.

## submit a server

anyone can submit an mcp server — no PR skills required.

1. open **Issues → New issue → "Submit a server"** (the issue form).
2. fill in name, github repo url, description, category, tags.
3. a github action (`triage server submission`) automatically:
   - detects issue-form submissions even if GitHub, the CLI, or an API client
     omits the template label, then applies `server-submission` itself
   - validates the repo is a real, public github repo
   - fetches live metadata (stars, last push)
   - rejects duplicates already in the directory (one status comment + `invalid` label)
   - opens a pull request adding the entry to `data/supplemental_servers.json`
   - safely revalidates edited/reopened issues and updates the same branch, PR,
     and status comment instead of creating duplicates
   - runs an hourly reconciliation sweep so transient event failures and bursts
     of simultaneous submissions do not leave issues unprocessed
4. a maintainer reviews + merges the PR. merging closes the submission issue and
   feeds the next daily `update data` run, which regenerates `servers.json`. you
   can also run the `update data` workflow manually to publish immediately.

hand-added servers live in `data/supplemental_servers.json` (source:
`"supplemental"`); the upstream `best-of-mcp-servers` list is merged on top
and de-duplicated by url. don't edit `data/servers.json` by hand — it's
regenerated.

## notes

- github pages is static. the 'service' here is the data + the update pipeline.
- avoid scraping too aggressively. the workflow uses the built-in `GITHUB_TOKEN` for github api calls.
