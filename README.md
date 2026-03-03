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

## monetization paths (non-spammy)

a static site can still make money if it has distribution.

- sponsorship slots
  - keep 3 small sponsor cards in `data/sponsors.json`
  - sell them as monthly placements (fixed price)

- paid curation
  - offer a “top 20 mcp servers for x” curated pack (pdf + config snippets)
  - link to a checkout (gumroad/stripe)

- paid alerts
  - free: the directory
  - paid: a weekly email of new/trending servers + your notes
  - use any newsletter provider; the site is just the landing page

## local dev

open `index.html` in a browser.

## notes

- github pages is static. the ‘service’ here is the data + the update pipeline.
- avoid scraping too aggressively. the workflow uses the built-in `GITHUB_TOKEN` for github api calls.
