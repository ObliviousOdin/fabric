# Team Pages

Team Pages is a bundled, dashboard-only Fabric plugin for lightweight internal
team hubs. It uses the existing dashboard plugin runtime and does not add a
model tool or change the agent core.

The plugin ships a useful starter in
`dashboard/dist/pages.default.json`. To personalize it, add page definitions to
`~/.fabric/config.yaml`:

```yaml
dashboard:
  team_pages:
    pages:
      - id: company
        nav_label: Company
        blocks:
          - id: company-title
            type: title
            eyebrow: Shared workspace
            title: Company home
            body: The context everyone should see first.
          - id: current-status
            type: status
            tone: success
            label: Operating normally
            text: No team action is needed.
          - id: links
            type: links
            title: Start here
            items:
              - label: Work board
                description: Active projects and agent work
                href: /kanban
```

Reload the dashboard after editing the file. Config pages replace the bundled
starter pages.

## Block schema

Every block needs a unique `id` and one of these `type` values:

- `title`: `eyebrow`, `title`, `body`
- `text`: `title`, `body`
- `markdown`: `content` (safe headings, paragraphs, lists, links, strong text,
  and inline code)
- `links`: `title`, then `items` with `label`, `description`, and `href`
- `kpi`: `title`, then `items` with `label`, `value`, and optional `detail`
- `table`: `title`, `columns`, and `rows`
- `status`: `tone`, `label`, and `text`; tone is `neutral`, `info`, `success`,
  or `warning`

Internal links must start with `/`. External links must use `https://`,
`http://`, or `mailto:`. Content is rendered as React elements; raw HTML is not
accepted.
