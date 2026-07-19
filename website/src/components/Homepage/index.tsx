import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import CodeBlock from "@theme/CodeBlock";
import styles from "./styles.module.css";

const surfaces = [
  {
    index: "01",
    name: "Desktop",
    copy: "A native workspace for chat, projects, previews, providers, memory, skills, and operations.",
    href: "/user-guide/desktop",
  },
  {
    index: "02",
    name: "Terminal",
    copy: "CLI and TUI workflows with real tools, streaming progress, approvals, and scriptable output.",
    href: "/user-guide/cli",
  },
  {
    index: "03",
    name: "Messaging",
    copy: "Long-running conversations across Telegram, Discord, Slack, Signal, email, and more.",
    href: "/user-guide/messaging",
  },
  {
    index: "04",
    name: "Web",
    copy: "A coordinated Workspace for agent operations and Admin console for runtime control.",
    href: "/user-guide/features/web-dashboard",
  },
  {
    index: "05",
    name: "IDE + API",
    copy: "ACP, MCP, and API surfaces that bring the same agent into editors and applications.",
    href: "/developer-guide/programmatic-integration",
  },
];

const routes = [
  {
    label: "Personal subscriptions",
    value: "ChatGPT",
    copy: "Connect a personal OpenAI subscription without pasting a long-lived API key.",
    href: "/guides/chatgpt-codex-subscription",
  },
  {
    label: "xAI subscription",
    value: "Grok",
    copy: "Connect SuperGrok or X Premium+ with the supported OAuth flow.",
    href: "/guides/xai-grok-oauth",
  },
  {
    label: "API providers",
    value: "Bring your key",
    copy: "Choose direct providers, routing services, or any compatible endpoint.",
    href: "/integrations/providers",
  },
  {
    label: "Local inference",
    value: "Ollama native",
    copy: "Keep model inference on your machine and verify the local-AI boundary.",
    href: "/guides/local-ollama-setup",
  },
];

const productViews = [
  {
    label: "Terminal UI",
    title: "The full agent in your terminal.",
    copy: "Commands, skills, status, approvals, and live tool work without leaving the keyboard.",
    image: "/img/product/fabric-tui-help.png",
    width: 1280,
    height: 720,
    alt: "Fabric TUI showing command help and session status inside the Fabric Light dashboard",
    href: "/user-guide/tui",
  },
  {
    label: "Web dashboard",
    title: "Operations and control, coordinated.",
    copy: "Move between Workspace operations and Admin controls without leaving the local runtime.",
    image: "/img/product/fabric-web-models.png",
    width: 1280,
    height: 720,
    alt: "Fabric web dashboard showing a connected local Ollama model",
    href: "/user-guide/features/web-dashboard",
  },
];

function Arrow(): React.JSX.Element {
  return (
    <span aria-hidden="true" className={styles.arrow}>
      →
    </span>
  );
}

function ProductView({
  view,
}: {
  view: (typeof productViews)[number];
}): React.JSX.Element {
  const imageUrl = useBaseUrl(view.image);

  return (
    <article className={styles.productCard}>
      <Link
        className={styles.productImageLink}
        to={view.href}
        aria-label={`Open guide: ${view.label}`}
      >
        <img
          src={imageUrl}
          width={view.width}
          height={view.height}
          alt={view.alt}
          loading="lazy"
        />
      </Link>
      <div className={styles.productCopy}>
        <p className={styles.productLabel}>{view.label}</p>
        <h3>{view.title}</h3>
        <p>{view.copy}</p>
        <Link to={view.href}>
          See how it works <Arrow />
        </Link>
      </div>
    </article>
  );
}

export default function Homepage(): React.JSX.Element {
  return (
    <main className={styles.page}>
      <section className={styles.hero} aria-labelledby="fabric-hero-title">
        <div className={styles.frame}>
          <div className={styles.heroGrid}>
            <div className={styles.heroCopy}>
              <p className={styles.eyebrow}>
                <span aria-hidden="true" className={styles.eyebrowRule} />
                Local-first multi-agent runtime
              </p>
              <h1 id="fabric-hero-title">
                One runtime, every agent operation in context.
              </h1>
              <p className={styles.heroLead}>
                Fabric connects conversations, agents, memory, automations,
                and runtime controls across desktop, terminal, web, messaging,
                and IDE workflows. Profiles keep each agent&apos;s configuration
                and memory isolated.
              </p>
              <div className={styles.heroActions}>
                <Link
                  className={styles.primaryAction}
                  to="/getting-started/installation"
                >
                  Install Fabric <Arrow />
                </Link>
                <Link
                  className={styles.secondaryAction}
                  to="/user-guide/desktop"
                >
                  Explore desktop
                </Link>
              </div>
              <ul className={styles.heroProof} aria-label="Fabric highlights">
                <li>macOS · Windows · Linux</li>
                <li>Subscriptions · APIs · Ollama</li>
                <li>Apache-2.0 licensed</li>
              </ul>
            </div>

            <figure
              className={styles.profileMap}
              aria-labelledby="fabric-profile-map-title"
            >
              <figcaption className={styles.mapHeader}>
                <span id="fabric-profile-map-title">PROFILE / MAIN</span>
                <span className={styles.ready}>
                  <span aria-hidden="true" /> Ready
                </span>
              </figcaption>
              <dl className={styles.profileInputs}>
                <div>
                  <dt>Model route</dt>
                  <dd>OAuth · API · local</dd>
                </div>
                <div>
                  <dt>Memory</dt>
                  <dd>Profile-scoped</dd>
                </div>
                <div>
                  <dt>Skills</dt>
                  <dd>Loaded on demand</dd>
                </div>
                <div>
                  <dt>Control</dt>
                  <dd>Explicit local policy</dd>
                </div>
              </dl>
              <div className={styles.fabricCore}>
                <span>Fabric core</span>
                <span>shared state · shared context · shared control</span>
              </div>
              <ul
                className={styles.surfaceMap}
                aria-label="Connected Fabric surfaces"
              >
                <li>Desktop</li>
                <li>Terminal</li>
                <li>Web</li>
                <li>Messaging</li>
                <li>IDE / API</li>
              </ul>
            </figure>
          </div>
        </div>
      </section>

      <section className={styles.ledger} aria-label="Core Fabric capabilities">
        <div className={styles.frame}>
          <dl className={styles.ledgerGrid}>
            <div>
              <dt>Models</dt>
              <dd>
                Route subscriptions, APIs, and local inference per profile.
              </dd>
            </div>
            <div>
              <dt>Memory</dt>
              <dd>
                Carry durable context across sessions without rebuilding it.
              </dd>
            </div>
            <div>
              <dt>Skills</dt>
              <dd>Load specialized playbooks only when the work needs them.</dd>
            </div>
            <div>
              <dt>Work</dt>
              <dd>Schedule, delegate, and continue long-running tasks.</dd>
            </div>
            <div>
              <dt>Control</dt>
              <dd>Keep risky actions behind visible, explicit approvals.</dd>
            </div>
          </dl>
        </div>
      </section>

      <section
        className={styles.surfacesSection}
        aria-labelledby="surfaces-title"
      >
        <div className={styles.frame}>
          <div className={styles.sectionHeading}>
            <p className={styles.sectionLabel}>One core / every surface</p>
            <h2 id="surfaces-title">Start anywhere. Keep the same agent.</h2>
            <p>
              Every surface can use the selected Fabric profile, so model
              routes, memory, skills, and session history stay aligned without
              turning profiles into team or tenant boundaries.
            </p>
          </div>
          <ol className={styles.surfaceList}>
            {surfaces.map((surface) => (
              <li key={surface.index}>
                <span className={styles.surfaceIndex}>{surface.index}</span>
                <h3>{surface.name}</h3>
                <p>{surface.copy}</p>
                <Link
                  to={surface.href}
                  aria-label={`Open guide: ${surface.name}`}
                >
                  Open guide <Arrow />
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className={styles.routesSection} aria-labelledby="routes-title">
        <div className={styles.frame}>
          <div className={styles.routesIntro}>
            <p className={styles.sectionLabel}>Choose your model route</p>
            <h2 id="routes-title">
              Use the account you have—or keep it local.
            </h2>
          </div>
          <div className={styles.routeList}>
            {routes.map((route) => (
              <Link
                className={styles.routeRow}
                key={route.label}
                to={route.href}
              >
                <span className={styles.routeLabel}>{route.label}</span>
                <strong>{route.value}</strong>
                <span className={styles.routeCopy}>{route.copy}</span>
                <Arrow />
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section
        className={styles.productSection}
        aria-labelledby="product-title"
      >
        <div className={styles.frame}>
          <div className={styles.productHeading}>
            <p className={styles.sectionLabel}>The real interfaces</p>
            <h2 id="product-title">One profile. Three ways to work.</h2>
            <p>
              These are live Fabric surfaces running against the same local
              profile—not concept art or staged mockups. The web
              Workspace/Admin foundation is available now; hosted tenancy,
              enforced role access, and durable enterprise ledgers remain
              staged backend work.{" "}
              <Link to="/user-guide/workspace-admin">See the delivery map.</Link>
            </p>
          </div>
          <div className={styles.productGrid}>
            {productViews.map((view) => (
              <ProductView key={view.label} view={view} />
            ))}
          </div>
        </div>
      </section>

      <section
        className={styles.compoundSection}
        aria-labelledby="compound-title"
      >
        <div className={styles.frame}>
          <div className={styles.compoundGrid}>
            <div className={styles.compoundIntro}>
              <p className={styles.sectionLabel}>Compound the work</p>
              <h2 id="compound-title">
                Memory that follows. Skills that deepen.
              </h2>
              <p>
                Fabric is built to improve the next session, not just finish the
                current prompt. Durable memory keeps useful context; skills turn
                repeatable methods into reusable capability.
              </p>
            </div>
            <div className={styles.compoundDetail}>
              <article>
                <span className={styles.detailNumber}>01</span>
                <h3>Profile memory</h3>
                <p>
                  Keep user context, project facts, and searchable session
                  history within the selected profile.
                </p>
                <Link to="/user-guide/features/memory">
                  Understand memory <Arrow />
                </Link>
              </article>
              <article>
                <span className={styles.detailNumber}>02</span>
                <h3>Progressive skills</h3>
                <p>
                  Discover and load focused instructions only when relevant,
                  preserving a stable conversation core.
                </p>
                <Link to="/user-guide/features/skills">
                  Explore skills <Arrow />
                </Link>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section
        className={styles.installSection}
        aria-labelledby="install-title"
      >
        <div className={styles.frame}>
          <div className={styles.installGrid}>
            <div>
              <p className={styles.sectionLabel}>
                Install from the public repository
              </p>
              <h2 id="install-title">
                Your first Fabric session is one command away.
              </h2>
              <p>
                Install on macOS, Linux, or WSL2, choose a model route, and
                verify the environment before running real work.
              </p>
              <div className={styles.installLinks}>
                <Link to="/getting-started/quickstart">
                  Follow the quickstart <Arrow />
                </Link>
                <a href="https://github.com/ObliviousOdin/fabric">
                  View source <span aria-hidden="true">↗</span>
                </a>
              </div>
            </div>
            <div className={styles.installCode}>
              <CodeBlock language="bash">{`curl -fsSL https://raw.githubusercontent.com/ObliviousOdin/fabric/main/scripts/install.sh | bash
fabric model
fabric status --deep`}</CodeBlock>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
