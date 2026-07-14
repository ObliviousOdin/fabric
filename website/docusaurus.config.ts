import { themes as prismThemes } from "prism-react-renderer";
import type { Config } from "@docusaurus/types";
import type * as Preset from "@docusaurus/preset-classic";

const config: Config = {
  title: "Fabric",
  tagline: "One runtime, woven through every surface",
  favicon: "img/favicon.ico",
  headTags: [
    {
      tagName: "link",
      attributes: {
        rel: "apple-touch-icon",
        sizes: "180x180",
        href: "/fabric/img/apple-touch-icon.png",
      },
    },
  ],

  url: "https://obliviousodin.github.io",
  baseUrl: "/fabric/",

  organizationName: 'ObliviousOdin',
  projectName: 'fabric',

  onBrokenLinks: "throw",
  onBrokenAnchors: "throw",

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: "throw",
    },
  },

  i18n: {
    defaultLocale: "en",
    locales: ["en"],
    localeConfigs: {
      en: {
        label: "English",
      },
    },
  },

  themes: [
    "@docusaurus/theme-mermaid",
    [
      require.resolve("@easyops-cn/docusaurus-search-local"),
      /** @type {import("@easyops-cn/docusaurus-search-local").PluginOptions} */
      {
        hashed: true,
        language: ["en"],
        indexBlog: false,
        docsRouteBasePath: "/",
        // Disabled: appends ?_highlight=... to URLs (before the #anchor),
        // which makes copy/pasted doc links ugly. Ctrl+F on the page is fine.
        highlightSearchTermsOnTargetPage: false,
        // Exclude the auto-generated per-skill catalog pages from search.
        // There are hundreds of them and they dominate results for generic
        // terms, drowning out the real user-guide / reference docs.
        // The two human-written catalog indexes (reference/skills-catalog,
        // reference/optional-skills-catalog) remain indexed.
        //
        // Note: ignoreFiles matches `route` (baseUrl stripped, no leading
        // slash). With baseUrl '/fabric/', `/fabric/user-guide/skills/bundled/x`
        // becomes 'user-guide/skills/bundled/x'.
        ignoreFiles: [
          /^user-guide\/skills\/bundled\//,
          /^user-guide\/skills\/optional\//,
        ],
      },
    ],
  ],

  plugins: [
    [
      "@docusaurus/plugin-client-redirects",
      {
        // Static-host redirects for renamed doc pages (GitHub Pages can't
        // do server-side redirects). Paths are relative to baseUrl (/fabric/).
        redirects: [
          {
            // Renamed when Automation Templates became Automation Blueprints.
            from: "/guides/automation-templates",
            to: "/guides/automation-blueprints",
          },
          {
            from: "/integrations/nous-portal",
            to: "/integrations/providers",
          },
          {
            from: "/guides/run-fabric-with-nous-portal",
            to: "/integrations/providers",
          },
          {
            from: "/guides/run-nemotron-3-ultra-free",
            to: "/integrations/providers",
          },
        ],
      },
    ],
  ],

  presets: [
    [
      "classic",
      {
        docs: {
          routeBasePath: "/", // Docs at the root of /docs/
          sidebarPath: "./sidebars.ts",
          editUrl: "https://github.com/ObliviousOdin/fabric/edit/main/website/",
        },
        blog: false,
        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: "img/fabric-mark.svg",
    metadata: [
      {
        name: "viewport",
        content: "width=device-width, initial-scale=1, viewport-fit=cover",
      },
    ],
    colorMode: {
      defaultMode: "dark",
      respectPrefersColorScheme: true,
    },
    docs: {
      sidebar: {
        hideable: true,
        autoCollapseCategories: true,
      },
    },
    navbar: {
      title: "Fabric",
      logo: {
        // The visible title already names the product. Keep the mark
        // decorative so screen readers announce the brand only once.
        alt: "",
        src: "img/fabric-mark.svg",
      },
      items: [
        { to: "/docs", label: "Docs", position: "left" },
        {
          to: "/skills",
          label: "Skills",
          position: "left",
        },
        {
          to: "/getting-started/installation",
          label: "Install",
          position: "right",
          className: "navbar__install",
        },
        {
          href: "https://github.com/ObliviousOdin/fabric",
          label: "GitHub",
          position: "right",
        },
        {
          type: "search",
          position: "right",
          className: "navbar__search-container",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Docs",
          items: [
            { label: "Getting Started", to: "/getting-started/quickstart" },
            { label: "User Guide", to: "/user-guide/" },
            { label: "Developer Guide", to: "/developer-guide/architecture" },
            { label: "Reference", to: "/reference/" },
          ],
        },
        {
          title: "Community",
          items: [
            {
              label: "GitHub Issues",
              href: "https://github.com/ObliviousOdin/fabric/issues",
            },
            { label: "Skills Hub", href: "https://agentskills.io" },
          ],
        },
        {
          title: "More",
          items: [
            { label: "Install Fabric", to: "/getting-started/installation" },
            {
              label: "GitHub",
              href: "https://github.com/ObliviousOdin/fabric",
            },
            {
              label: "Apache-2.0 license",
              href: "https://github.com/ObliviousOdin/fabric/blob/main/LICENSE",
            },
            {
              label: "Attribution notices",
              href: "https://github.com/ObliviousOdin/fabric/blob/main/NOTICE",
            },
          ],
        },
      ],
      copyright: `Fabric contributors · Apache License 2.0 · ${new Date().getFullYear()}`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ["bash", "yaml", "json", "python", "toml"],
    },
    mermaid: {
      theme: { light: "neutral", dark: "dark" },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
