import {
  SiFigma,
  SiGithub,
  SiGitlab,
  SiLinear,
  SiNotion,
  SiPostgresql,
  SiSentry,
  SiStripe,
  SiSupabase,
  SiVercel
} from '@icons-pack/react-simple-icons'
import type { ComponentType, ReactNode, SVGProps } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { PageLoader } from '@/components/page-loader'
import { StatusDot, type StatusTone } from '@/components/status-dot'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  getMcpCatalog,
  getMessagingPlatforms,
  listOAuthProviders,
  type McpCatalogEntry,
  type MessagingPlatformInfo,
  updateMessagingPlatform
} from '@/fabric'
import { type Translations, useI18n } from '@/i18n'
import { ChevronRight, Globe, KeyRound, MessageCircle, Wrench } from '@/lib/icons'
import { normalize } from '@/lib/text'
import { cn } from '@/lib/utils'
import { notify, notifyError } from '@/store/notifications'
import { startManualProviderOAuth } from '@/store/onboarding'
import { runGatewayRestart } from '@/store/system-actions'
import type { OAuthProvider } from '@/types/fabric'

import { useRefreshHotkey } from '../hooks/use-refresh-hotkey'
import { PlatformAvatar } from '../messaging/platform-icon'
import { PageSearchShell, type PageShellTab } from '../page-search-shell'
import { MESSAGING_ROUTE, SETTINGS_ROUTE, SKILLS_ROUTE } from '../routes'
import type { SetStatusbarItemGroup } from '../shell/statusbar-controls'

// The hub groups every connection into one of four families. "All" is a
// synthetic tab that shows them together; the rest filter to one family.
type Category = 'accounts' | 'messaging' | 'network' | 'tools'
type Tab = 'all' | Category

const TABS: readonly Tab[] = ['all', 'messaging', 'tools', 'accounts', 'network']

interface ConnectionsViewProps extends React.ComponentProps<'section'> {
  // Inline pages receive this so they can contribute status-bar items; the hub
  // has none, so it is accepted and ignored (parity with MessagingView).
  setStatusbarItemGroup?: SetStatusbarItemGroup
}

const PILL_TONE: Record<StatusTone, string> = {
  good: 'bg-primary/10 text-primary',
  muted: 'bg-muted text-muted-foreground',
  warn: 'bg-amber-500/10 text-amber-600 dark:text-amber-300',
  bad: 'bg-destructive/10 text-destructive'
}

// One normalized card, whatever its source. `search` is the lowercased haystack
// the search box filters against; `render` supplies the row-trailing action.
interface ConnectionItem {
  avatar: ReactNode
  category: Category
  description: string
  id: string
  name: string
  render: ReactNode
  search: string
  statusLabel: string
  tone: StatusTone
}

// ---------------------------------------------------------------------------
// Messaging → real platform status from the gateway catalog.
// ---------------------------------------------------------------------------

function messagingStatus(
  platform: MessagingPlatformInfo,
  c: Translations['connections']
): { label: string; tone: StatusTone } {
  if (!platform.configured) {
    return { label: c.statusNotSetUp, tone: 'muted' }
  }

  if (!platform.enabled) {
    return { label: c.statusOff, tone: 'muted' }
  }

  if (platform.state === 'connected') {
    return { label: c.statusConnected, tone: 'good' }
  }

  if (platform.state === 'fatal' || platform.state === 'startup_failed') {
    return { label: c.statusError, tone: 'bad' }
  }

  return { label: c.statusNeedsAttention, tone: 'warn' }
}

// ---------------------------------------------------------------------------
// Tools → the Fabric-curated MCP catalog (GitHub, Linear, …). Brand glyphs
// mirror the MCP page's treatment: a curated simpleicons mark on a soft tint,
// letter monogram otherwise. We never fetch remote favicons (a configured MCP
// URL can be a private host).
// ---------------------------------------------------------------------------

const TOOL_BRAND: Record<string, { Icon: ComponentType<SVGProps<SVGSVGElement>>; color: string }> = {
  figma: { Icon: SiFigma, color: '#F24E1E' },
  github: { Icon: SiGithub, color: '#181717' },
  gitlab: { Icon: SiGitlab, color: '#FC6D26' },
  linear: { Icon: SiLinear, color: '#5E6AD2' },
  notion: { Icon: SiNotion, color: '#000000' },
  postgres: { Icon: SiPostgresql, color: '#4169E1' },
  postgresql: { Icon: SiPostgresql, color: '#4169E1' },
  sentry: { Icon: SiSentry, color: '#362D59' },
  stripe: { Icon: SiStripe, color: '#635BFF' },
  supabase: { Icon: SiSupabase, color: '#3FCF8E' },
  vercel: { Icon: SiVercel, color: '#000000' }
}

const toolBrand = (name: string) => {
  const lower = name.toLowerCase()

  return TOOL_BRAND[lower] ?? Object.entries(TOOL_BRAND).find(([key]) => lower.includes(key))?.[1] ?? null
}

// GitHub and Linear are the two the user cares about most; float them (and the
// other well-known dev tools) to the front, keeping the backend order otherwise.
const TOOL_PRIORITY = ['github', 'linear', 'notion', 'sentry', 'stripe', 'supabase', 'vercel', 'gitlab', 'figma']

function ToolAvatar({ name }: { name: string }) {
  const brand = toolBrand(name)

  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-grid size-6 shrink-0 place-items-center rounded-md text-[length:var(--conversation-caption-font-size)] font-medium',
        !brand && 'bg-(--ui-bg-tertiary) text-(--ui-text-tertiary)'
      )}
      style={brand ? { backgroundColor: `color-mix(in srgb, ${brand.color} 16%, transparent)` } : undefined}
    >
      {brand ? <brand.Icon className="size-3.5" style={{ color: brand.color }} /> : name.charAt(0).toUpperCase()}
    </span>
  )
}

function toolStatus(entry: McpCatalogEntry, c: Translations['connections']): { label: string; tone: StatusTone } {
  if (!entry.installed) {
    return { label: c.statusNotSetUp, tone: 'muted' }
  }

  return entry.enabled ? { label: c.statusConnected, tone: 'good' } : { label: c.statusOff, tone: 'muted' }
}

// ---------------------------------------------------------------------------
// Network → the backend connection + secure remote access (Tailscale). The
// deeper Tailscale enrollment flow lands separately; here we route to the
// gateway settings where remote access is configured.
// ---------------------------------------------------------------------------

interface NetworkEntry {
  descKey: 'gatewayDesc' | 'tailscaleDesc'
  id: string
  nameKey: 'gatewayTitle' | 'tailscaleTitle'
  target: string
}

const NETWORK_ENTRIES: readonly NetworkEntry[] = [
  { descKey: 'gatewayDesc', id: 'gateway', nameKey: 'gatewayTitle', target: `${SETTINGS_ROUTE}?tab=gateway` },
  { descKey: 'tailscaleDesc', id: 'tailscale', nameKey: 'tailscaleTitle', target: `${SETTINGS_ROUTE}?tab=gateway` }
]

// ---------------------------------------------------------------------------

function StatePill({ children, tone }: { children: string; tone: StatusTone }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.66rem] font-medium',
        PILL_TONE[tone]
      )}
    >
      <StatusDot tone={tone} />
      {children}
    </span>
  )
}

function LinkAction({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button className="shrink-0" onClick={onClick} size="sm" variant="text">
      {label}
      <ChevronRight className="size-3.5" />
    </Button>
  )
}

function ConnectionCard({ item }: { item: ConnectionItem }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) p-3">
      {item.avatar}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 truncate text-[length:var(--conversation-text-font-size)] font-medium">
            {item.name}
          </span>
          <StatePill tone={item.tone}>{item.statusLabel}</StatePill>
        </div>
        <p className="mt-0.5 line-clamp-1 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
          {item.description}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">{item.render}</div>
    </div>
  )
}

type SectionDescKey = 'accountsDesc' | 'messagingDesc' | 'networkDesc' | 'toolsDesc'

const SECTION_META: Record<Category, { descKey: SectionDescKey; icon: typeof Globe }> = {
  accounts: { descKey: 'accountsDesc', icon: KeyRound },
  messaging: { descKey: 'messagingDesc', icon: MessageCircle },
  network: { descKey: 'networkDesc', icon: Globe },
  tools: { descKey: 'toolsDesc', icon: Wrench }
}

function Section({
  category,
  items,
  title
}: {
  category: Category
  items: ConnectionItem[]
  title: string
}) {
  const { t } = useI18n()
  const c = t.connections

  if (items.length === 0) {
    return null
  }

  const meta = SECTION_META[category]
  const Icon = meta.icon

  return (
    <section className="mb-6">
      <div className="mb-2 flex items-center gap-2">
        <Icon className="size-4 text-muted-foreground" />
        <h3 className="text-[0.9375rem] font-semibold tracking-tight">{title}</h3>
        <span className="text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
          {items.length}
        </span>
      </div>
      <p className="mb-3 text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)">
        {c[meta.descKey]}
      </p>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {items.map(item => (
          <ConnectionCard item={item} key={item.id} />
        ))}
      </div>
    </section>
  )
}

export function ConnectionsView({ setStatusbarItemGroup: _setStatusbarItemGroup, ...props }: ConnectionsViewProps) {
  const { t } = useI18n()
  const c = t.connections
  const navigate = useNavigate()

  const [platforms, setPlatforms] = useState<MessagingPlatformInfo[] | null>(null)
  const [tools, setTools] = useState<McpCatalogEntry[] | null>(null)
  const [providers, setProviders] = useState<OAuthProvider[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState<Tab>('all')
  const [savingToggle, setSavingToggle] = useState<string | null>(null)

  const restartGatewayAction = { label: t.commandCenter.restartGateway, onClick: () => void runGatewayRestart() }

  // Each source loads best-effort: one backend hiccup dims that family instead
  // of blanking the whole hub. The first pass flips `loading` off; refreshes are
  // silent so the hotkey never flashes a full-page spinner.
  const refresh = useCallback(async (initial = false) => {
    if (initial) {
      setLoading(true)
    }

    const [messaging, catalog, oauth] = await Promise.allSettled([
      getMessagingPlatforms(),
      getMcpCatalog(),
      listOAuthProviders()
    ])

    if (messaging.status === 'fulfilled') {
      setPlatforms(messaging.value.platforms)
    } else if (initial) {
      setPlatforms([])
    }

    if (catalog.status === 'fulfilled') {
      setTools(catalog.value.entries)
    } else if (initial) {
      setTools([])
    }

    if (oauth.status === 'fulfilled') {
      setProviders(oauth.value.providers)
    } else if (initial) {
      setProviders([])
    }

    if (initial) {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh(true)
  }, [refresh])

  useRefreshHotkey(() => void refresh())

  async function toggleMessaging(platform: MessagingPlatformInfo, enabled: boolean) {
    setSavingToggle(platform.id)

    try {
      await updateMessagingPlatform(platform.id, { enabled })
      setPlatforms(
        current =>
          current?.map(row =>
            row.id === platform.id
              ? { ...row, enabled, state: enabled ? (row.configured ? 'pending_restart' : 'not_configured') : 'disabled' }
              : row
          ) ?? current
      )
      notify({
        kind: 'success',
        title: enabled ? c.platformEnabled(platform.name) : c.platformDisabled(platform.name),
        message: c.restartToApply,
        action: restartGatewayAction
      })
    } catch (err) {
      notifyError(err, c.toggleFailed(platform.name))
    } finally {
      setSavingToggle(null)
    }
  }

  async function connectProvider(provider: OAuthProvider) {
    try {
      startManualProviderOAuth(provider.id)
    } catch (err) {
      notifyError(err, c.connectFailed(provider.name))
    }
  }

  const messagingItems = useMemo<ConnectionItem[]>(() => {
    return (platforms ?? []).map(platform => {
      const status = messagingStatus(platform, c)

      return {
        avatar: <PlatformAvatar platformId={platform.id} platformName={platform.name} />,
        category: 'messaging',
        description: platform.description,
        id: `messaging:${platform.id}`,
        name: platform.name,
        render: (
          <>
            <Switch
              aria-label={platform.enabled ? c.disableAria(platform.name) : c.enableAria(platform.name)}
              checked={platform.enabled}
              disabled={savingToggle === platform.id}
              onCheckedChange={value => void toggleMessaging(platform, value)}
              size="xs"
            />
            <LinkAction label={c.setUp} onClick={() => navigate(`${MESSAGING_ROUTE}?platform=${platform.id}`)} />
          </>
        ),
        search: `${platform.name} ${platform.id} ${platform.description}`.toLowerCase(),
        statusLabel: status.label,
        tone: status.tone
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- c/navigate stable; re-derive on data + toggle state
  }, [platforms, savingToggle])

  const toolItems = useMemo<ConnectionItem[]>(() => {
    const sorted = [...(tools ?? [])].sort((a, b) => {
      const ai = TOOL_PRIORITY.indexOf(a.name.toLowerCase())
      const bi = TOOL_PRIORITY.indexOf(b.name.toLowerCase())

      return (ai === -1 ? TOOL_PRIORITY.length : ai) - (bi === -1 ? TOOL_PRIORITY.length : bi)
    })

    return sorted.map(entry => {
      const status = toolStatus(entry, c)

      return {
        avatar: <ToolAvatar name={entry.name} />,
        category: 'tools',
        description: entry.description,
        id: `tool:${entry.name}`,
        name: prettyToolName(entry.name),
        render: (
          <LinkAction
            label={entry.installed ? c.manage : c.setUp}
            onClick={() => navigate(`${SKILLS_ROUTE}?tab=mcp&server=${encodeURIComponent(entry.name)}`)}
          />
        ),
        search: `${entry.name} ${entry.description}`.toLowerCase(),
        statusLabel: status.label,
        tone: status.tone
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- c/navigate stable; re-derive on data
  }, [tools])

  const accountItems = useMemo<ConnectionItem[]>(() => {
    return (providers ?? []).map(provider => {
      const connected = provider.status.logged_in

      return {
        avatar: (
          <span className="inline-grid size-6 shrink-0 place-items-center rounded-md bg-(--ui-bg-tertiary) text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-tertiary)">
            {provider.name.charAt(0).toUpperCase()}
          </span>
        ),
        category: 'accounts',
        description: connected ? c.accountConnected : c.accountConnectHint,
        id: `account:${provider.id}`,
        name: provider.name,
        render: connected ? (
          <LinkAction label={c.manage} onClick={() => navigate(`${SETTINGS_ROUTE}?tab=providers&pview=accounts`)} />
        ) : (
          <Button className="shrink-0" onClick={() => void connectProvider(provider)} size="sm">
            {c.connect}
          </Button>
        ),
        search: `${provider.name} ${provider.id}`.toLowerCase(),
        statusLabel: connected ? c.statusConnected : c.statusNotConnected,
        tone: connected ? 'good' : 'muted'
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- c/navigate stable; re-derive on data
  }, [providers])

  const networkItems = useMemo<ConnectionItem[]>(() => {
    return NETWORK_ENTRIES.map(entry => ({
      avatar: (
        <span className="inline-grid size-6 shrink-0 place-items-center rounded-md bg-(--ui-bg-tertiary) text-(--ui-text-tertiary)">
          <Globe className="size-3.5" />
        </span>
      ),
      category: 'network',
      description: c[entry.descKey],
      id: `network:${entry.id}`,
      name: c[entry.nameKey],
      render: <LinkAction label={c.configure} onClick={() => navigate(entry.target)} />,
      search: `${c[entry.nameKey]} ${entry.id} ${c[entry.descKey]}`.toLowerCase(),
      statusLabel: c.statusOptional,
      tone: 'muted' as StatusTone
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- c/navigate stable
  }, [])

  const byCategory: Record<Category, ConnectionItem[]> = {
    accounts: accountItems,
    messaging: messagingItems,
    network: networkItems,
    tools: toolItems
  }

  const filter = (items: ConnectionItem[]) => {
    const q = normalize(query)

    return q ? items.filter(item => item.search.includes(q)) : items
  }

  const visibleCategories: Category[] = tab === 'all' ? ['messaging', 'tools', 'accounts', 'network'] : [tab]

  const total = messagingItems.length + toolItems.length + accountItems.length + networkItems.length
  const matchCount = visibleCategories.reduce((sum, category) => sum + filter(byCategory[category]).length, 0)

  const tabs: PageShellTab[] = TABS.map(id => ({
    id,
    label: c.tabs[id],
    meta:
      id === 'all'
        ? total
        : loading && byCategory[id].length === 0
          ? null
          : byCategory[id].length
  }))

  const sectionTitle: Record<Category, string> = {
    accounts: c.accountsTitle,
    messaging: c.messagingTitle,
    network: c.networkTitle,
    tools: c.toolsTitle
  }

  return (
    <PageSearchShell
      {...props}
      activeTab={tab}
      onSearchChange={setQuery}
      onTabChange={id => setTab(id as Tab)}
      searchHints={[c.hintSlack, c.hintGithub, c.hintTailscale]}
      searchPlaceholder={c.search}
      searchValue={query}
      tabs={tabs}
    >
      {loading ? (
        <PageLoader label={c.loading} />
      ) : (
        <div className="h-full min-h-0 overflow-y-auto px-4 py-4">
          {matchCount === 0 ? (
            <div className="grid min-h-40 place-items-center text-center text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
              {query ? c.noResults(query) : c.empty}
            </div>
          ) : (
            visibleCategories.map(category => (
              <Section
                category={category}
                items={filter(byCategory[category])}
                key={category}
                title={sectionTitle[category]}
              />
            ))
          )}
        </div>
      )}
    </PageSearchShell>
  )
}

// MCP catalog names are ids ("github", "linear"); title-case for display while
// leaving known acronyms alone enough to read.
function prettyToolName(name: string): string {
  return name
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, ch => ch.toUpperCase())
}
