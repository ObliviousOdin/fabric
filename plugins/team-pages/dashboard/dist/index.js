(function () {
  "use strict";

  const SDK = window.__FABRIC_PLUGIN_SDK__;
  const registry = window.__FABRIC_PLUGINS__;
  if (!SDK || !registry) return;

  const React = SDK.React;
  const {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
  } = SDK.hooks;
  const Icons = SDK.icons || {};

  function icon(name, props) {
    const Component = Icons[name];
    if (!Component) return null;
    return React.createElement(Component, Object.assign({
      size: 16,
      strokeWidth: 1.8,
      "aria-hidden": true,
      focusable: false,
    }, props || {}));
  }

  const DEFAULT_PAGES_URL =
    "/dashboard-plugins/team-pages/dist/pages.default.json";
  const SELECTED_PAGE_KEY = "fabric-team-pages:selected";
  const MAX_PAGES = 24;
  const MAX_BLOCKS = 40;
  const ALLOWED_BLOCKS = new Set([
    "title",
    "text",
    "markdown",
    "links",
    "kpi",
    "table",
    "status",
  ]);
  const STATUS_TONES = new Set(["neutral", "info", "success", "warning"]);

  const scriptPath = (function () {
    try {
      return new URL(
        document.currentScript ? document.currentScript.src : "",
        window.location.href,
      ).pathname;
    } catch (_) {
      return "";
    }
  })();
  const marker = "/dashboard-plugins/team-pages/";
  const markerIndex = scriptPath.indexOf(marker);
  const dashboardBasePath = markerIndex >= 0 ? scriptPath.slice(0, markerIndex) : "";

  const EMERGENCY_PAGES = [
    {
      id: "team-home",
      nav_label: "Team home",
      blocks: [
        {
          id: "fallback-title",
          type: "title",
          eyebrow: "Shared workspace",
          title: "Team home",
          body: "Your shared team page is ready to configure.",
        },
        {
          id: "fallback-status",
          type: "status",
          tone: "warning",
          label: "Starter content unavailable",
          text: "Add dashboard.team_pages.pages to config.yaml, then reload the dashboard.",
        },
      ],
    },
  ];

  function stringValue(value, maxLength, fallback) {
    if (typeof value !== "string") return fallback || "";
    return value.trim().slice(0, maxLength);
  }

  function objectValue(value) {
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  }

  function safeHref(value) {
    const href = stringValue(value, 2048, "");
    if (!href || /[\u0000-\u001f\u007f]/.test(href)) return null;
    if (href.startsWith("/") && !href.startsWith("//")) return href;
    if (/^https?:\/\//i.test(href) || /^mailto:/i.test(href)) return href;
    return null;
  }

  function normalizeBlock(rawValue, pageId, index) {
    const raw = objectValue(rawValue);
    if (!raw) return null;
    const type = stringValue(raw.type, 24, "").toLowerCase();
    if (!ALLOWED_BLOCKS.has(type)) return null;

    const block = {
      id: stringValue(raw.id, 80, pageId + "-block-" + index),
      type: type,
    };

    if (type === "title") {
      block.eyebrow = stringValue(raw.eyebrow, 80, "");
      block.title = stringValue(raw.title, 160, "Untitled page");
      block.body = stringValue(raw.body, 1200, "");
      return block;
    }

    if (type === "text") {
      block.title = stringValue(raw.title, 160, "");
      block.body = stringValue(raw.body, 4000, "");
      return block.title || block.body ? block : null;
    }

    if (type === "markdown") {
      block.content = stringValue(raw.content, 12000, "");
      return block.content ? block : null;
    }

    if (type === "status") {
      const requestedTone = stringValue(raw.tone, 24, "neutral").toLowerCase();
      block.tone = STATUS_TONES.has(requestedTone) ? requestedTone : "neutral";
      block.label = stringValue(raw.label, 120, "Status");
      block.text = stringValue(raw.text, 1200, "");
      return block;
    }

    if (type === "links") {
      block.title = stringValue(raw.title, 160, "Links");
      block.items = (Array.isArray(raw.items) ? raw.items : [])
        .slice(0, 24)
        .map(function (itemValue) {
          const item = objectValue(itemValue);
          if (!item) return null;
          const href = safeHref(item.href);
          const label = stringValue(item.label, 160, "");
          if (!href || !label) return null;
          return {
            label: label,
            description: stringValue(item.description, 600, ""),
            href: href,
          };
        })
        .filter(Boolean);
      return block.items.length ? block : null;
    }

    if (type === "kpi") {
      block.title = stringValue(raw.title, 160, "Key metrics");
      block.items = (Array.isArray(raw.items) ? raw.items : [])
        .slice(0, 24)
        .map(function (itemValue) {
          const item = objectValue(itemValue);
          if (!item) return null;
          const label = stringValue(item.label, 120, "");
          const value = stringValue(String(item.value == null ? "" : item.value), 120, "");
          if (!label || !value) return null;
          return {
            label: label,
            value: value,
            detail: stringValue(item.detail, 240, ""),
          };
        })
        .filter(Boolean);
      return block.items.length ? block : null;
    }

    block.title = stringValue(raw.title, 160, "Table");
    block.columns = (Array.isArray(raw.columns) ? raw.columns : [])
      .slice(0, 12)
      .map(function (column) { return stringValue(String(column), 160, ""); })
      .filter(Boolean);
    if (!block.columns.length) return null;
    block.rows = (Array.isArray(raw.rows) ? raw.rows : [])
      .slice(0, 100)
      .filter(Array.isArray)
      .map(function (row) {
        return block.columns.map(function (_, columnIndex) {
          const cell = row[columnIndex];
          return stringValue(String(cell == null ? "" : cell), 1000, "");
        });
      });
    return block;
  }

  function normalizePages(rawPages) {
    if (!Array.isArray(rawPages)) return [];
    const usedPageIds = new Set();
    return rawPages.slice(0, MAX_PAGES).map(function (rawValue, pageIndex) {
      const raw = objectValue(rawValue);
      if (!raw) return null;
      let id = stringValue(raw.id, 80, "page-" + pageIndex)
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, "-")
        .replace(/^-+|-+$/g, "");
      if (!id) id = "page-" + pageIndex;
      const baseId = id;
      let suffix = pageIndex;
      while (usedPageIds.has(id)) {
        id = baseId + "-" + suffix;
        suffix += 1;
      }
      usedPageIds.add(id);

      const usedBlockIds = new Set();
      const blocks = (Array.isArray(raw.blocks) ? raw.blocks : [])
        .slice(0, MAX_BLOCKS)
        .map(function (block, blockIndex) {
          const normalized = normalizeBlock(block, id, blockIndex);
          if (!normalized) return null;
          const baseBlockId = normalized.id;
          let blockSuffix = blockIndex;
          while (usedBlockIds.has(normalized.id)) {
            normalized.id = baseBlockId + "-" + blockSuffix;
            blockSuffix += 1;
          }
          usedBlockIds.add(normalized.id);
          return normalized;
        })
        .filter(Boolean);

      if (!blocks.length) return null;
      return {
        id: id,
        nav_label: stringValue(raw.nav_label || raw.label, 80, "Page " + (pageIndex + 1)),
        blocks: blocks,
      };
    }).filter(Boolean);
  }

  function configPages(configValue) {
    const config = objectValue(configValue);
    if (!config) return { present: false, pages: [] };
    const dashboard = objectValue(config.dashboard);
    const root = objectValue(config.team_pages);
    const nested = dashboard
      ? objectValue(dashboard.team_pages || dashboard.teamPages)
      : null;
    const section = nested || root;
    if (!section || !Object.prototype.hasOwnProperty.call(section, "pages")) {
      return { present: false, pages: [] };
    }
    return { present: true, pages: normalizePages(section.pages) };
  }

  async function loadBundledPages() {
    if (typeof SDK.authedFetch !== "function") {
      throw new Error("The dashboard plugin SDK cannot load bundled content.");
    }
    const response = await SDK.authedFetch(DEFAULT_PAGES_URL);
    if (!response.ok) throw new Error("Starter pages returned " + response.status + ".");
    const payload = await response.json();
    const pages = normalizePages(objectValue(payload) ? payload.pages : []);
    if (!pages.length) throw new Error("Starter pages are empty.");
    return pages;
  }

  async function loadConfiguredPages() {
    if (!SDK.api || typeof SDK.api.getConfig !== "function") {
      return { present: false, pages: [] };
    }
    return configPages(await SDK.api.getConfig());
  }

  async function loadPageModel() {
    const results = await Promise.allSettled([
      loadConfiguredPages(),
      loadBundledPages(),
    ]);
    const configured = results[0].status === "fulfilled"
      ? results[0].value
      : { present: false, pages: [] };

    if (configured.present && configured.pages.length) {
      return {
        pages: configured.pages,
        source: "Configured in config.yaml",
        notice: "",
      };
    }

    if (results[1].status === "fulfilled") {
      return {
        pages: results[1].value,
        source: "Starter pages",
        notice: configured.present
          ? "Custom pages could not be read, so the starter pages are shown."
          : "",
      };
    }

    return {
      pages: normalizePages(EMERGENCY_PAGES),
      source: "Fallback page",
      notice: "Starter content could not be loaded. Add pages in config.yaml and reload.",
    };
  }

  function resolvedHref(href) {
    if (!href || !href.startsWith("/")) return href;
    return (dashboardBasePath || "") + href;
  }

  function isExternalHref(href) {
    return /^https?:\/\//i.test(href);
  }

  function InlineContent({ text }) {
    const nodes = [];
    const pattern = /\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`/g;
    let cursor = 0;
    let match;
    let index = 0;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
      const token = match[0];
      if (token.startsWith("**")) {
        nodes.push(React.createElement("strong", { key: "strong-" + index }, token.slice(2, -2)));
      } else if (token.startsWith("`")) {
        nodes.push(React.createElement("code", { key: "code-" + index }, token.slice(1, -1)));
      } else {
        const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
        const href = linkMatch ? safeHref(linkMatch[2]) : null;
        if (linkMatch && href) {
          const external = isExternalHref(href);
          nodes.push(React.createElement(
            "a",
            {
              key: "link-" + index,
              href: resolvedHref(href),
              target: external ? "_blank" : undefined,
              rel: external ? "noopener noreferrer" : undefined,
            },
            linkMatch[1],
            external
              ? React.createElement("span", { className: "ftp-sr-only" }, " (opens in a new tab)")
              : null,
          ));
        } else {
          nodes.push(token);
        }
      }
      cursor = match.index + token.length;
      index += 1;
    }
    if (cursor < text.length) nodes.push(text.slice(cursor));
    return React.createElement(React.Fragment, null, nodes);
  }

  function MarkdownBlock({ block }) {
    const content = useMemo(function () {
      const lines = block.content.replace(/\r\n?/g, "\n").split("\n");
      const output = [];
      let index = 0;
      while (index < lines.length) {
        const line = lines[index].trim();
        if (!line) {
          index += 1;
          continue;
        }

        const heading = /^(#{1,3})\s+(.+)$/.exec(line);
        if (heading) {
          const level = heading[1].length === 1 ? "h3" : "h4";
          output.push(React.createElement(
            level,
            { key: "heading-" + index },
            React.createElement(InlineContent, { text: heading[2] }),
          ));
          index += 1;
          continue;
        }

        if (/^-\s+/.test(line)) {
          const items = [];
          const start = index;
          while (index < lines.length && /^-\s+/.test(lines[index].trim())) {
            items.push(lines[index].trim().replace(/^-\s+/, ""));
            index += 1;
          }
          output.push(React.createElement(
            "ul",
            { key: "list-" + start },
            items.map(function (item, itemIndex) {
              return React.createElement(
                "li",
                { key: "item-" + itemIndex },
                React.createElement(InlineContent, { text: item }),
              );
            }),
          ));
          continue;
        }

        if (/^\d+\.\s+/.test(line)) {
          const items = [];
          const start = index;
          while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
            items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
            index += 1;
          }
          output.push(React.createElement(
            "ol",
            { key: "ordered-" + start },
            items.map(function (item, itemIndex) {
              return React.createElement(
                "li",
                { key: "item-" + itemIndex },
                React.createElement(InlineContent, { text: item }),
              );
            }),
          ));
          continue;
        }

        const paragraphs = [line];
        const start = index;
        index += 1;
        while (
          index < lines.length &&
          lines[index].trim() &&
          !/^(#{1,3})\s+/.test(lines[index].trim()) &&
          !/^-\s+/.test(lines[index].trim()) &&
          !/^\d+\.\s+/.test(lines[index].trim())
        ) {
          paragraphs.push(lines[index].trim());
          index += 1;
        }
        output.push(React.createElement(
          "p",
          { key: "paragraph-" + start },
          React.createElement(InlineContent, { text: paragraphs.join(" ") }),
        ));
      }
      return output;
    }, [block.content]);

    return React.createElement("section", { className: "ftp-block ftp-markdown" }, content);
  }

  function TitleBlock({ block }) {
    return React.createElement(
      "header",
      { className: "ftp-page-title" },
      block.eyebrow
        ? React.createElement("p", { className: "ftp-eyebrow" }, block.eyebrow)
        : null,
      React.createElement("h2", null, block.title),
      block.body ? React.createElement("p", { className: "ftp-page-summary" }, block.body) : null,
    );
  }

  function TextBlock({ block }) {
    return React.createElement(
      "section",
      { className: "ftp-block ftp-text-block" },
      block.title ? React.createElement("h3", null, block.title) : null,
      block.body ? React.createElement("p", null, block.body) : null,
    );
  }

  function StatusBlock({ block }) {
    return React.createElement(
      "section",
      {
        className: "ftp-block ftp-status ftp-status-" + block.tone,
        "aria-label": "Status: " + block.label,
      },
      React.createElement("span", { className: "ftp-status-dot", "aria-hidden": "true" }),
      React.createElement(
        "div",
        null,
        React.createElement("h3", null, block.label),
        block.text ? React.createElement("p", null, block.text) : null,
      ),
    );
  }

  function KpiBlock({ block }) {
    return React.createElement(
      "section",
      { className: "ftp-block" },
      React.createElement("h3", null, block.title),
      React.createElement(
        "ul",
        { className: "ftp-kpi-grid" },
        block.items.map(function (item, index) {
          return React.createElement(
            "li",
            { key: item.label + "-" + index },
            React.createElement("span", { className: "ftp-kpi-label" }, item.label),
            React.createElement("strong", null, item.value),
            item.detail ? React.createElement("span", { className: "ftp-kpi-detail" }, item.detail) : null,
          );
        }),
      ),
    );
  }

  function LinksBlock({ block }) {
    return React.createElement(
      "section",
      { className: "ftp-block" },
      React.createElement("h3", null, block.title),
      React.createElement(
        "ul",
        { className: "ftp-links" },
        block.items.map(function (item, index) {
          const external = isExternalHref(item.href);
          return React.createElement(
            "li",
            { key: item.label + "-" + index },
            React.createElement(
              "a",
              {
                href: resolvedHref(item.href),
                target: external ? "_blank" : undefined,
                rel: external ? "noopener noreferrer" : undefined,
              },
              React.createElement(
                "span",
                { className: "ftp-link-copy" },
                React.createElement("strong", null, item.label),
                item.description ? React.createElement("span", null, item.description) : null,
              ),
              React.createElement(
                "span",
                { className: "ftp-link-arrow", "aria-hidden": "true" },
                icon(external ? "ExternalLink" : "ArrowRight"),
              ),
              external
                ? React.createElement("span", { className: "ftp-sr-only" }, " (opens in a new tab)")
                : null,
            ),
          );
        }),
      ),
    );
  }

  function TableBlock({ block }) {
    return React.createElement(
      "section",
      { className: "ftp-block" },
      React.createElement("h3", null, block.title),
      React.createElement(
        "div",
        { className: "ftp-table-scroll", tabIndex: 0 },
        React.createElement(
          "table",
          null,
          React.createElement("caption", { className: "ftp-sr-only" }, block.title),
          React.createElement(
            "thead",
            null,
            React.createElement(
              "tr",
              null,
              block.columns.map(function (column, index) {
                return React.createElement("th", { key: column + "-" + index, scope: "col" }, column);
              }),
            ),
          ),
          React.createElement(
            "tbody",
            null,
            block.rows.map(function (row, rowIndex) {
              return React.createElement(
                "tr",
                { key: "row-" + rowIndex },
                row.map(function (cell, cellIndex) {
                  const Tag = cellIndex === 0 ? "th" : "td";
                  return React.createElement(
                    Tag,
                    cellIndex === 0
                      ? { key: "cell-" + cellIndex, scope: "row" }
                      : { key: "cell-" + cellIndex },
                    cell,
                  );
                }),
              );
            }),
          ),
        ),
      ),
    );
  }

  function BlockRenderer({ block }) {
    if (block.type === "title") return React.createElement(TitleBlock, { block: block });
    if (block.type === "text") return React.createElement(TextBlock, { block: block });
    if (block.type === "markdown") return React.createElement(MarkdownBlock, { block: block });
    if (block.type === "status") return React.createElement(StatusBlock, { block: block });
    if (block.type === "kpi") return React.createElement(KpiBlock, { block: block });
    if (block.type === "links") return React.createElement(LinksBlock, { block: block });
    if (block.type === "table") return React.createElement(TableBlock, { block: block });
    return null;
  }

  function LoadingState() {
    return React.createElement(
      "div",
      { className: "ftp-loading", role: "status", "aria-live": "polite" },
      React.createElement("span", { className: "ftp-loading-line ftp-loading-line-short" }),
      React.createElement("span", { className: "ftp-loading-line" }),
      React.createElement("span", { className: "ftp-sr-only" }, "Loading team pages"),
    );
  }

  function TeamPages() {
    const [model, setModel] = useState(null);
    const [selectedId, setSelectedId] = useState("");
    const tabRefs = useRef([]);

    useEffect(function () {
      let cancelled = false;
      loadPageModel().then(function (nextModel) {
        if (cancelled) return;
        let saved = "";
        try { saved = window.localStorage.getItem(SELECTED_PAGE_KEY) || ""; } catch (_) {}
        const initial = nextModel.pages.some(function (page) { return page.id === saved; })
          ? saved
          : nextModel.pages[0].id;
        setModel(nextModel);
        setSelectedId(initial);
      });
      return function () { cancelled = true; };
    }, []);

    const activePage = useMemo(function () {
      if (!model) return null;
      return model.pages.find(function (page) { return page.id === selectedId; }) || model.pages[0];
    }, [model, selectedId]);

    const selectPage = useCallback(function (id) {
      setSelectedId(id);
      try { window.localStorage.setItem(SELECTED_PAGE_KEY, id); } catch (_) {}
    }, []);

    const moveSelection = useCallback(function (event, index) {
      if (!model) return;
      const count = model.pages.length;
      let nextIndex = index;
      if (event.key === "ArrowDown" || event.key === "ArrowRight") {
        nextIndex = (index + 1) % count;
      } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
        nextIndex = (index - 1 + count) % count;
      } else if (event.key === "Home") {
        nextIndex = 0;
      } else if (event.key === "End") {
        nextIndex = count - 1;
      } else {
        return;
      }
      event.preventDefault();
      const page = model.pages[nextIndex];
      selectPage(page.id);
      if (tabRefs.current[nextIndex]) tabRefs.current[nextIndex].focus();
    }, [model, selectPage]);

    return React.createElement(
      "div",
      { className: "fabric-team-pages" },
      React.createElement(
        "header",
        { className: "ftp-shell-header" },
        React.createElement(
          "div",
          null,
          React.createElement("p", { className: "ftp-eyebrow" }, "Shared workspace"),
          React.createElement("h1", null, "Team"),
          React.createElement("p", null, "Internal pages for the context, signals, and links your team needs."),
        ),
        model
          ? React.createElement("span", { className: "ftp-source" }, model.source)
          : null,
      ),
      model && model.notice
        ? React.createElement("p", { className: "ftp-notice", role: "alert" }, model.notice)
        : null,
      !model
        ? React.createElement(LoadingState)
        : React.createElement(
            "div",
            { className: "ftp-workspace" },
            React.createElement(
              "nav",
              { className: "ftp-page-picker", "aria-label": "Team pages" },
              React.createElement("p", { className: "ftp-picker-label" }, "Pages"),
              React.createElement(
                "div",
                { className: "ftp-tabs", role: "tablist", "aria-label": "Choose a team page" },
                model.pages.map(function (page, index) {
                  const selected = activePage && page.id === activePage.id;
                  return React.createElement(
                    "button",
                    {
                      key: page.id,
                      ref: function (node) { tabRefs.current[index] = node; },
                      id: "ftp-tab-" + page.id,
                      type: "button",
                      role: "tab",
                      tabIndex: selected ? 0 : -1,
                      "aria-selected": selected,
                      "aria-controls": "ftp-panel-" + page.id,
                      onClick: function () { selectPage(page.id); },
                      onKeyDown: function (event) { moveSelection(event, index); },
                    },
                    page.nav_label,
                  );
                }),
              ),
            ),
            activePage
              ? React.createElement(
                  "section",
                  {
                    key: activePage.id,
                    className: "ftp-page-content",
                    "aria-label": activePage.nav_label + " team page",
                  },
                  React.createElement(
                    "div",
                    {
                      id: "ftp-panel-" + activePage.id,
                      className: "ftp-page-panel",
                      role: "tabpanel",
                      tabIndex: 0,
                      "aria-labelledby": "ftp-tab-" + activePage.id,
                    },
                    activePage.blocks.map(function (block) {
                      return React.createElement(BlockRenderer, { key: block.id, block: block });
                    }),
                  ),
                )
              : null,
          ),
    );
  }

  registry.register("team-pages", TeamPages);
})();
