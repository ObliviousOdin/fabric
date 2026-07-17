export type Locale =
  | "en"
  | "zh"
  | "zh-hant"
  | "ja"
  | "de"
  | "es"
  | "fr"
  | "tr"
  | "uk"
  | "af"
  | "ko"
  | "it"
  | "ga"
  | "pt"
  | "ru"
  | "hu";

export interface Translations {
  // ── Common ──
  common: {
    save: string;
    saving: string;
    cancel: string;
    close: string;
    confirm: string;
    delete: string;
    refresh: string;
    retry: string;
    search: string;
    loading: string;
    create: string;
    creating: string;
    set: string;
    replace: string;
    clear: string;
    live: string;
    off: string;
    enabled: string;
    disabled: string;
    active: string;
    inactive: string;
    unknown: string;
    untitled: string;
    none: string;
    form: string;
    noResults: string;
    of: string;
    page: string;
    msgs: string;
    tools: string;
    match: string;
    other: string;
    configured: string;
    removed: string;
    failedToToggle: string;
    failedToRemove: string;
    failedToReveal: string;
    collapse: string;
    expand: string;
    general: string;
    messaging: string;
    // Optional: non-English locales fall back to the English literal in the
    // component until translated, matching the enriched-profiles keys.
    gateway?: string;
    gatewayHint?: string;
    copyId?: string;
    pluginLoadFailed: string;
    pluginNotRegistered: string;
  };

  // ── Shared agent-status vocabulary (WORK-section primitives) ──
  // Optional group: `AgentStatusBadge` falls back to the raw status word
  // for locales that haven't translated it yet.
  agentStatus?: {
    live: string;
    idle: string;
    scheduled: string;
    paused: string;
    failed: string;
    done: string;
  };

  // ── Shared capability-state vocabulary (CAPABILITIES-section primitives) ──
  // Optional group: capability badges fall back to the English state words
  // from `capability-state.ts` for locales that haven't translated it yet.
  capabilities?: {
    enabled: string;
    active: string;
    installed: string;
    ready: string;
    disabled: string;
    inactive: string;
    needsSetup: string;
    needsAuth: string;
    unavailable: string;
    missing: string;
    reachable: string;
    unreachable: string;
  };

  // ── Shared gateway-restart lifecycle (CONNECT-section primitives, CN3) ──
  // Optional group: `RestartBanner` falls back to the English literals for
  // locales that haven't translated it yet.
  gatewayRestart?: {
    /** Action label on the restart-needed banner. */
    restartNow: string;
    /** Action label while the restart POST is in flight. */
    restarting: string;
    /** Default restart-needed copy when the page supplies none. */
    needed: string;
  };

  // ── System page (operator's console, Y-requirements) ──
  // Optional group (CN6): call sites fall back to the English literals
  // until translated (O5 pattern).
  system?: {
    /** Section headings (Y1 order). */
    host: string;
    gateway: string;
    portal: string;
    curator: string;
    memory: string;
    credentialPool: string;
    operations: string;
    checkpoints: string;
    shellHooks: string;
    /** Shell hooks header/empty-state action (Y10/Y14). */
    newHook: string;
    /** Y14 empty-hooks EmptyState. */
    noHooksTitle: string;
    noHooksDescription: string;
    /** Fetch-failure banner prefix (optional — English fallback inline). */
    sectionsFailed?: string;
  };

  // ── Chat rail (Agent card + Activity feed, CH-requirements) ──
  // Optional group: the chat rail falls back to English literals until
  // locales translate it.
  chatRail?: {
    /** Chrome label of the Agent card. */
    agent: string;
    /** Chrome label of the Activity feed card. */
    activity: string;
    /** Trailing label on a tool row awaiting its tool.complete. */
    running: string;
    /** Transient state line while the agent streams reply text. */
    responding: string;
    /** Transient state line during reasoning/thinking deltas. */
    reasoning: string;
    /** Pinned row while an approval.request awaits a terminal response. */
    waitingApproval: string;
  };

  /** New three-panel Chat chrome; locales fall back to English incrementally. */
  chatWorkspace?: {
    agentChat: string;
    chooseSecondaryPanel: string;
    context: string;
    conversations: string;
    newConversation: string;
    openContext: string;
    openConversations: string;
    panels: string;
    secondaryPanel: string;
    taskAndAgentContext: string;
  };

  // ── App shell ──
  app: {
    brand: string;
    brandShort: string;
    closeNavigation: string;
    closeModelTools: string;
    footer: {
      org: string;
    };
    activeSessionsLabel: string;
    gatewayStatusLabel: string;
    gatewayStrip: {
      failed: string;
      off: string;
      running: string;
      starting: string;
      stopped: string;
    };
    nav: {
      analytics: string;
      chat: string;
      config: string;
      cron: string;
      documentation: string;
      keys: string;
      logs: string;
      models: string;
      profiles: string;
      plugins: string;
      sessions: string;
      skills: string;
    };
    /** Workspace/Admin IA labels; optional while locale packs catch up. */
    enterpriseNav?: {
      activity: string;
      admin: string;
      advanced: string;
      agents: string;
      aiRuntime: string;
      approvals: string;
      automations: string;
      channelsEvents: string;
      conversations: string;
      design?: string;
      experience: string;
      help: string;
      home: string;
      insights: string;
      integrations: string;
      knowledge: string;
      memory: string;
      securityAccess: string;
      system: string;
      workBoard: string;
      workspace: string;
    };
    /**
     * Sidebar nav section labels. Optional — non-English locales fall back
     * to the English literals at the call site until translated.
     */
    navSections?: {
      capabilities: string;
      connect: string;
      observe: string;
      system: string;
      work: string;
    };
    modelToolsSheetSubtitle: string;
    modelToolsSheetTitle: string;
    navigation: string;
    /** Docs-iframe offline fallback (optional — English fallback inline). */
    docsUnreachableTitle?: string;
    docsUnreachableDescription?: string;
    openDocumentation: string;
    openNavigation: string;
    pluginNavSection: string;
    sessionsActiveCount: string;
    statusOverview: string;
    system: string;
    webUi: string;
    /** Optional — fall back to English literals until translated. */
    managingProfile?: string;
    currentProfileOption?: string;
    managingProfileBanner?: string;
  };

  /** Design workspace; locales fall back to English until translated. */
  design?: {
    briefLabel: string;
    briefPlaceholder: string;
    contractDescription: string;
    contractTitle: string;
    deliverableLabel: string;
    fidelity: string;
    fidelityHigh: string;
    fidelityWireframe: string;
    phases: readonly [string, string, string, string, string];
    reviewHint: string;
    start: string;
    subtitle: string;
    systemLabel: string;
    title: string;
  };

  // ── Status page ──
  status: {
    actionFailed: string;
    actionFinished: string;
    actions: string;
    agent: string;
    connected: string;
    connectedPlatforms: string;
    disabled?: string;
    disconnected: string;
    error: string;
    failed: string;
    gateway: string;
    gatewayFailedToStart: string;
    lastUpdate: string;
    noneRunning: string;
    notRunning: string;
    pid: string;
    platformDisconnected: string;
    platformError: string;
    activeSessions: string;
    recentSessions: string;
    restartGateway: string;
    restartGatewayConfirmMessage?: string;
    restartGatewayConfirmTitle?: string;
    restartingGateway: string;
    running: string;
    runningRemote: string;
    startFailed: string;
    starting: string;
    startedInBackground: string;
    stopped: string;
    updateFabric: string;
    updateFabricConfirmMessage?: string;
    updateFabricConfirmNow?: string;
    updateFabricConfirmTitle?: string;
    updatingFabric: string;
    waitingForOutput: string;
  };

  // ── Sessions page ──
  sessions: {
    title: string;
    history: string;
    overview: string;
    searchPlaceholder: string;
    noSessions: string;
    noMatch: string;
    startConversation: string;
    noMessages: string;
    untitledSession: string;
    deleteSession: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    sessionDeleted: string;
    failedToDelete: string;
    deleteEmpty: string;
    deleteEmptyConfirmTitle: string;
    deleteEmptyConfirmMessage: string;
    emptySessionsDeleted: string;
    failedToDeleteEmpty: string;
    selectSession: string;
    selectAllOnPage: string;
    clearSelection: string;
    selectedCount: string;
    deleteSelected: string;
    deleteSelectedConfirmTitle: string;
    deleteSelectedConfirmMessage: string;
    selectedSessionsDeleted: string;
    failedToDeleteSelected: string;
    resumeInChat: string;
    newChat: string;
    previousPage: string;
    nextPage: string;
    /**
     * WORK-section "run ledger" revamp keys (spec S1–S11). Optional —
     * call sites fall back to the English literals until translated,
     * matching the `agentStatus` / `channels` pattern.
     */
    ledger?: {
      statsLabel: string;
      statsSessions: string;
      statsActiveNow: string;
      statsInStore: string;
      statsMessages: string;
      statsArchived: string;
      gatewayLabel: string;
      toolbarLabel: string;
      sourceFilterLabel: string;
      allSources: string;
      openChat: string;
      clearSearch: string;
      clearFilter: string;
      noSourceTitle: string;
      /** `{source}` placeholder = the active source filter. */
      noSourceDescription: string;
      loadFailed: string;
      loadEarlier: string;
      contextCwd: string;
      contextBranch: string;
      contextEndReason: string;
      contextModel: string;
    };
    roles: {
      user: string;
      assistant: string;
      system: string;
      tool: string;
    };
  };

  // ── Analytics page ──
  analytics: {
    period: string;
    totalTokens: string;
    totalSessions: string;
    apiCalls: string;
    dailyTokenUsage: string;
    dailyBreakdown: string;
    perModelBreakdown: string;
    topSkills: string;
    skill: string;
    loads: string;
    edits: string;
    lastUsed: string;
    input: string;
    output: string;
    total: string;
    noUsageData: string;
    startSession: string;
    date: string;
    model: string;
    tokens: string;
    perDayAvg: string;
    acrossModels: string;
    inOut: string;
    // Optional workload-report keys (Observe revamp, spec A1–A11):
    // non-English locales fall back to the English literal at the call
    // site until translated, matching the `sessions.ledger` pattern.
    workload?: {
      runs: string;
      apiCalls: string;
      skillActions: string;
      toolCalls: string;
      tokens: string;
      estCost: string;
      /** Compact one-row notice shown while token analytics are gated off. */
      estimatesHiddenSummary: string;
      configLink: string;
      recentRuns: string;
      /** `{limit}` placeholder = the recent-runs fetch bound (e.g. "last 20"). */
      lastRunsQualifier: string;
      openInSessions: string;
      noRunsYet: string;
      noRunsHint: string;
      openChat: string;
      busiestTools: string;
      tool: string;
      calls: string;
      /** "+{count} more" footer under the truncated tools table. */
      moreTools: string;
      toolCountsNote: string;
      runsBySource: string;
    };
  };

  // ── Models page ──
  models: {
    modelsUsed: string;
    estimatedCost: string;
    tokens: string;
    sessions: string;
    avgPerSession: string;
    apiCalls: string;
    toolCalls: string;
    noModelsData: string;
    startSession: string;
    // Optional loadout keys (Capabilities revamp, spec M1–M11): non-English
    // locales fall back to the English literal at the call site until
    // translated, matching the `analytics.workload` pattern.
    loadout?: {
      /** Chrome label of the assignment surface (M2). */
      loadout: string;
      /** Load-bearing subtitle — assignments apply to new sessions only. */
      appliesToNewSessions: string;
      mainModel: string;
      auxiliaryTasks: string;
      mixtureOfAgents: string;
      /** Italic-muted placeholder for an unset provider/model slot. */
      unset: string;
      /** One-line inline warning when `/api/model/auxiliary` fails (M11). */
      auxUnavailable: string;
      /** Destructive banner when the analytics load fails (M11). */
      loadFailed: string;
      /** Compact one-row token-gate notice (CAP8, Observe A1.2 pattern). */
      tokensHiddenSummary: string;
      configLink: string;
    };
  };

  // ── MCP page ──
  // Optional group (CAPABILITIES revamp, spec X1–X11): call sites fall back
  // to the English literals until a locale translates it.
  mcp?: {
    addServer: string;
    yourServers: string;
    /** `{n}` = configured servers, `{m}` = enabled servers (X3 summary). */
    serversSummary: string;
    noServersTitle: string;
    noServersDescription: string;
    catalog: string;
    catalogIntro: string;
    noCatalogTitle: string;
    restartNote: string;
    test: string;
    login: string;
    waitingForBrowser: string;
    connectedNoTools: string;
    /** `{n}` placeholders (mono meta-line counts). */
    envVarCount: string;
    envVarsCount: string;
    toolsEnabledCount: string;
    promptsCount: string;
    resourcesCount: string;
    // Installed-state chip label lives in the shared `capabilities` group.
    install: string;
    installing: string;
    installingBackground: string;
    loadServersFailed: string;
    loadCatalogFailed: string;
  };

  // ── Logs page ──
  logs: {
    title: string;
    autoRefresh: string;
    file: string;
    level: string;
    component: string;
    lines: string;
    noLogLines: string;
    // Optional: non-English locales fall back to the English literal at the
    // call site until translated.
    noLinesHint?: string;
    jumpToLatest?: string;
    // Observe revamp (spec L4/L5/L9/L11/L13) — optional: non-English
    // locales fall back to the English literals at the call site.
    searchPlaceholder?: string;
    clearSearch?: string;
    /** `{term}` placeholder = the active search/session term. */
    noMatchesFor?: string;
    filterSession?: string;
    streaming?: string;
    streamingScrolled?: string;
    streamPaused?: string;
    pausedHere?: string;
    earlierScrolledOut?: string;
    /** `{n}` placeholder = fetched-window size (chip/tally `title`s). */
    inViewHint?: string;
    errAbbrev?: string;
    warnAbbrev?: string;
  };

  // ── Cron page ──
  cron: {
    confirmDeleteMessage: string;
    confirmDeleteTitle: string;
    newJob: string;
    nameOptional: string;
    namePlaceholder: string;
    prompt: string;
    promptPlaceholder: string;
    schedule: string;
    schedulePlaceholder: string;
    scheduleMode: string;
    scheduleModes: {
      interval: string;
      daily: string;
      weekly: string;
      monthly: string;
      once: string;
      custom: string;
      intervalEvery: string;
      intervalUnit: string;
      unitMinutes: string;
      unitHours: string;
      unitDays: string;
      timeOfDay: string;
      weekdays: string;
      weekdaysShort: [string, string, string, string, string, string, string];
      dayOfMonth: string;
      onceAt: string;
      customLabel: string;
      customPlaceholder: string;
      customHint: string;
      preview: string;
      previewEmpty: string;
    };
    scheduleDescribe: {
      none: string;
      everyMinutes: string;
      everyHours: string;
      everyDays: string;
      dailyAt: string;
      weeklyAt: string;
      monthlyAt: string;
      onceAt: string;
    };
    deliverTo: string;
    scheduledJobs: string;
    noJobs: string;
    // Optional: non-English locales fall back to `noJobs` / the English
    // literal at the call site until translated.
    noJobsTitle?: string;
    noJobsDescription?: string;
    last: string;
    next: string;
    pause: string;
    resume: string;
    triggerNow: string;
    // Optional agentic-revamp strings (C2 summary strip, C6 run-history
    // drawer, C12/C13 states). Non-English locales fall back to the English
    // literals at the call sites until translated.
    agents?: {
      statJobs: string;
      statNextRun: string;
      statPaused: string;
      statFailing: string;
      runHistory: string;
      jobsLoadFailed: string;
      runsLoadFailed: string;
      noRunsTitle: string;
      noRunsDescription: string;
      openInSessions: string;
    };
    delivery: {
      local: string;
      telegram: string;
      discord: string;
      slack: string;
      email: string;
      needsHomeChannel?: string;
      noneConfigured?: string;
    };
  };

  // ── Channels page ──
  /**
   * Optional — the page is otherwise un-i18n'd; call sites fall back to the
   * English literals until translated (same pattern as `commandPalette`).
   */
  channels?: {
    noChannelsTitle: string;
    noChannelsDescription: string;
    /** Load-failure banner copy (CONNECT revamp H5). */
    loadFailed?: string;
    /** `title` on the sessions-count usage-evidence segment (H6). */
    sessionsEvidenceTitle?: string;
  };

  // ── Webhooks page ──
  /**
   * Optional — the page is otherwise un-i18n'd; call sites fall back to
   * the English literals until translated (O5 pattern, CN6).
   */
  webhooks?: {
    noSubscriptionsTitle: string;
    noSubscriptionsDescription: string;
    loadFailed: string;
  };

  // ── Pairing page ──
  /**
   * Optional — call sites fall back to the English literals until
   * translated (CN6, same O5 pattern as `channels`).
   */
  pairing?: {
    pendingHeading: string;
    approvedHeading: string;
    noPendingTitle: string;
    noPendingDescription: string;
    noApprovedTitle: string;
    noApprovedDescription: string;
    loadFailed: string;
    clearPending: string;
    clearPendingConfirm: string;
  };

  // ── Files page ──
  /** Optional — same CN6/O5 fallback pattern as `pairing`. */
  files?: {
    noFilesTitle: string;
    noFilesDescription: string;
  };

  // ── Plugins page ──
  pluginsPage: {
    contextEngineLabel: string;
    dashboardSlots: string;
    disableRuntime: string;
    enableAfterInstall: string;
    enableRuntime: string;
    forceReinstall: string;
    headline: string;
    identifierLabel: string;
    inactive: string;
    installBtn: string;
    installHeading: string;
    installHint: string;
    memoryProviderLabel: string;
    missingEnvWarn: string;
    noDashboardTab: string;
    openTab: string;
    orphanHeading: string;
    pluginListHeading: string;
    providerDefaults: string;
    providersHeading: string;
    providersHint: string;
    refreshDashboard: string;
    removeConfirm: string;
    removeHint: string;
    rescanHeading: string;
    rescanHint: string;
    runtimeHeading: string;
    saveProviders: string;
    savedProviders: string;
    sourceBadge: string;
    authRequired: string;
    authRequiredHint: string;
    updateGit: string;
    versionBadge: string;
    showInSidebar: string;
    hideFromSidebar: string;
    // Optional CAPABILITIES-revamp strings (spec P1 loadout-first order,
    // P2 corrected state chips, P6–P8 states). Non-English locales fall
    // back to the English literals at the call sites until translated
    // (same pattern as `cron.agents`).
    agents?: {
      enginesLabel: string;
      hubLoadFailed: string;
      noPluginsTitle: string;
      noPluginsDescription: string;
      installCta: string;
      // `needs auth` chip label lives in the shared `capabilities` group.
      stateEffectNote: string;
    };
  };

  // ── Profiles page ──
  profiles: {
    newProfile: string;
    name: string;
    namePlaceholder: string;
    nameRequired: string;
    nameRule: string;
    invalidName: string;
    cloneFrom: string;
    cloneFromNone: string;
    allProfiles: string;
    noProfiles: string;
    defaultBadge: string;
    hasEnv: string;
    model: string;
    skills: string;
    rename: string;
    editSoul: string;
    soulSection: string;
    soulPlaceholder: string;
    saveSoul: string;
    soulSaved: string;
    openInTerminal: string;
    commandCopied: string;
    copyFailed: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    created: string;
    deleted: string;
    renamed: string;
    // Optional keys added for the enriched profiles experience. Non-English
    // locales fall back to the English literal in the component until
    // translated, so these are optional to avoid churning every locale file.
    activeProfile?: string;
    activeBadge?: string;
    setActive?: string;
    activeSet?: string;
    gatewayRunning?: string;
    gatewayStopped?: string;
    gatewayRunningWarning?: string;
    aliasBadge?: string;
    description?: string;
    descriptionPlaceholder?: string;
    noDescription?: string;
    editDescription?: string;
    descriptionSaved?: string;
    reviewBadge?: string;
    autoGenerate?: string;
    generating?: string;
    describeFailed?: string;
    distribution?: string;
    advancedOptions?: string;
    cloneAll?: string;
    noSkillsOption?: string;
    descriptionOptional?: string;
    modelOptional?: string;
    modelInherit?: string;
    modelLoading?: string;
    modelNone?: string;
    editModel?: string;
    modelSaved?: string;
    modelSelect?: string;
    actions?: string;
    manageSkills?: string;
    activeSetHint?: string;
    // CONNECT+SYSTEM revamp (PR1/PR7). Optional — English fallbacks at the
    // call sites until translated (O5 pattern).
    /** PR1 `title` copy: active = sticky default for new runs, current = this dashboard's scope. */
    activeVsCurrentTitle?: string;
    /** PR7 roster load-failure banner text. */
    loadFailed?: string;
  };

  // ── Skills page ──
  skills: {
    title: string;
    searchPlaceholder: string;
    enabledOf: string;
    all: string;
    categories: string;
    filters: string;
    noSkills: string;
    noSkillsMatch: string;
    skillCount: string;
    resultCount: string;
    noDescription: string;
    toolsets: string;
    toolsetLabel: string;
    noToolsetsMatch: string;
    setupNeeded: string;
    disabledForCli: string;
    more: string;
    /** Optional — fall back to English literals until translated. */
    profileSelector?: string;
    currentProfile?: string;
    managingProfile?: string;
    /**
     * CAPABILITIES revamp (K-requirements). Optional group — the Skills
     * page falls back to the English literals at the call sites until
     * translated (same pattern as `sessions.ledger`).
     */
    inventory?: {
      /** Chrome label of the rail provenance-filter group (K2). */
      provenance: string;
      provenanceHub: string;
      provenanceBundled: string;
      /** `agent` provenance is labeled "custom" in UI copy (K2). */
      provenanceAgent: string;
      /** `{count} use{s}` skill-usage meta segment (K4/K5). */
      uses: string;
      /** `{count} tool{s}` toolset meta segment (K7). */
      toolCount: string;
      /** `~{count} calls · 30d` best-effort toolset usage join (K7/R20). */
      callsMeta: string;
      /** `title` caveat on the calls segment (R14/R20). */
      callsCaveat: string;
      /** R16 `title` copy on toolset/skill state — no hot-swap implied. */
      appliesNewSessions: string;
      loadFailed: string;
      noSkillsTitle: string;
      noMatchTitle: string;
      noToolsetsTitle: string;
      clearSearch: string;
      clearFilter: string;
    };
  };

  // ── Config page ──
  config: {
    configPath: string;
    filters: string;
    sections: string;
    exportConfig: string;
    importConfig: string;
    resetDefaults: string;
    resetScopeTooltip: string;
    confirmResetScope: string;
    resetScopeToast: string;
    rawYaml: string;
    searchResults: string;
    fields: string;
    noFieldsMatch: string;
    configSaved: string;
    yamlConfigSaved: string;
    failedToSave: string;
    failedToSaveYaml: string;
    failedToLoadRaw: string;
    configImported: string;
    invalidJson: string;
    // CONNECT+SYSTEM revamp (CF4/CF5). Optional — English fallbacks at
    // the call sites until translated (O5 pattern).
    /** CF5 truthfulness note rendered once under the config path. */
    effectNote?: string;
    /** CF4 shared load-failure banner (config *and* schema both failed). */
    loadFailed?: string;
    /** CF4 no-match search action button. */
    clearSearch?: string;
    categories: {
      general: string;
      agent: string;
      terminal: string;
      display: string;
      delegation: string;
      memory: string;
      compression: string;
      security: string;
      browser: string;
      voice: string;
      tts: string;
      stt: string;
      logging: string;
      discord: string;
      auxiliary: string;
    };
  };

  // ── Env / Keys page ──
  env: {
    changesNote: string;
    confirmClearMessage: string;
    confirmClearTitle: string;
    description: string;
    enterValue: string;
    getKey: string;
    hideAdvanced: string;
    hideValue: string;
    keysCount: string;
    llmProviders: string;
    notConfigured: string;
    notSet: string;
    providersConfigured: string;
    replaceCurrentValue: string;
    showAdvanced: string;
    showLess: string;
    showMore: string;
    showValue: string;
    customTitle: string;
    customHint: string;
    customConfigured: string;
    addCustomKey: string;
    customKeyName: string;
    customKeyNamePlaceholder: string;
    add: string;
    invalidKeyName: string;
    // CONNECT+SYSTEM revamp (E3/E7/E8). Optional — English fallbacks at the
    // call sites until translated (O5 pattern).
    /** E7 probe action label ("Test"). */
    testKey?: string;
    /** E7 probe in-flight label ("Testing…"). */
    testingKey?: string;
    /** E7 success chip label for an accepted credential. */
    keyAccepted?: string;
    /** E7 warning chip label when the probe could not reach the provider. */
    keyUnreachable?: string;
    /** E3 specific 429 message for the reveal rate limit (§0.7). */
    revealRateLimited?: string;
    /** E8 load-failure banner text. */
    loadFailed?: string;
  };

  // ── OAuth ──
  oauth: {
    title: string;
    providerLogins: string;
    description: string;
    connected: string;
    expired: string;
    notConnected: string;
    runInTerminal: string;
    noProviders: string;
    /** Persistent load-failure banner (optional — English fallback inline). */
    loadFailed?: string;
    login: string;
    disconnect: string;
    managedExternally: string;
    copied: string;
    copyCode: string;
    copyFailed: string;
    cli: string;
    copyCliCommand: string;
    connect: string;
    chooseAccountOwner: string;
    personalAccount: string;
    personalAccountDescription: string;
    managedAccount: string;
    managedAccountDescription: string;
    managedUnavailableTitle: string;
    managedOpenAIInstructions: string;
    managedXaiInstructions: string;
    emailFabric: string;
    continueToProvider: string;
    backToAccountChoice: string;
    deviceCodeSecurityWarning: string;
    sessionExpires: string;
    initiatingLogin: string;
    exchangingCode: string;
    connectedClosing: string;
    loginFailed: string;
    sessionExpired: string;
    reOpenAuth: string;
    reOpenVerification: string;
    submitCode: string;
    pasteCode: string;
    waitingAuth: string;
    enterCodePrompt: string;
    pkceStep1: string;
    pkceStep2: string;
    pkceStep3: string;
    flowLabels: {
      pkce: string;
      device_code: string;
      external: string;
    };
    expiresIn: string;
  };

  // ── Language switcher ──
  language: {
    switchTo: string;
  };

  // ── Theme switcher ──
  theme: {
    title: string;
    switchTheme: string;
    /** Font-override section (optional — locales fall back to English). */
    fontTitle?: string;
    fontDefault?: string;
    fontDefaultHint?: string;
    fontSans?: string;
    fontSerif?: string;
    fontMono?: string;
    /** Appearance + contrast controls (optional — English fallback). */
    appearance?: string;
    appearanceDark?: string;
    appearanceLight?: string;
    appearanceSystem?: string;
    highContrast?: string;
    /** Terminal appearance section (optional — English fallback). */
    terminalTitle?: string;
    terminalHint?: string;
    terminalSchemeDefault?: string;
    terminalSchemeDefaultHint?: string;
    terminalFontTitle?: string;
    terminalFontDefault?: string;
    terminalFontSizeTitle?: string;
    terminalFontSizeAuto?: string;
  };

  // ── Command palette & keyboard shortcuts ──
  /**
   * Optional — non-English locales fall back to the English literals at the
   * call sites until translated (same pattern as `app.navSections`).
   */
  commandPalette?: {
    title: string;
    placeholder: string;
    pages: string;
    actions: string;
    themes: string;
    noResults: string;
    openPalette: string;
    showShortcuts: string;
    shortcutsTitle: string;
    toggleSidebar: string;
    scopeGlobal: string;
    hintNavigate: string;
    hintSelect: string;
    hintClose: string;
  };

  // ── Achievements plugin (plugins/fabric-achievements) ──
  achievements: {
    hero: {
      kicker: string;
      title: string;
      subtitle: string;
      scan_subtitle: string;
    };
    actions: {
      rescan: string;
    };
    stats: {
      unlocked: string;
      unlocked_hint: string;
      discovered: string;
      discovered_hint: string;
      secrets: string;
      secrets_hint: string;
      highest_tier: string;
      highest_tier_hint: string;
      latest: string;
      latest_hint_empty: string;
      none_yet: string;
    };
    state: {
      unlocked: string;
      discovered: string;
      secret: string;
    };
    tier: {
      target: string;
      hidden: string;
      complete: string;
      objective: string;
    };
    progress: {
      hidden: string;
    };
    scan: {
      building_headline: string;
      building_detail: string;
      starting_headline: string;
      progress_detail: string;
      idle_detail: string;
    };
    guide: {
      tiers_header: string;
      secret_header: string;
      secret_body: string;
      scan_status_header: string;
      scan_status_body: string;
      what_scanned_header: string;
      what_scanned_body: string;
    };
    card: {
      share_title: string;
      share_label: string;
      share_text: string;
      how_to_reveal: string;
      what_counts: string;
      evidence_label: string;
      evidence_session_fallback: string;
      no_evidence: string;
    };
    latest: {
      header: string;
    };
    empty: {
      no_secrets_header: string;
      no_secrets_body: string;
    };
    filters: {
      all_categories: string;
      visibility_all: string;
      visibility_unlocked: string;
      visibility_discovered: string;
      visibility_secret: string;
    };
    share: {
      dialog_label: string;
      header: string;
      close: string;
      rendering: string;
      card_alt: string;
      error_generic: string;
      x_title: string;
      x_button: string;
      copy_title: string;
      copy_button: string;
      copied: string;
      download_button: string;
      hint: string;
      clipboard_unsupported: string;
      tweet_text: string;
    };
    // Team leaderboard views. Optional so the other locales keep compiling
    // and fall back to the English strings baked into the plugin bundle (see
    // tx() in plugins/fabric-achievements/dashboard/dist/index.js). Translate
    // these per-locale as a follow-up.
    nav?: {
      achievements: string;
      leaderboard: string;
    };
    team?: {
      kicker: string;
      hero_title: string;
      hero_subtitle: string;
      loading: string;
      working: string;
      starting: string;
      generic_error: string;
      create_title: string;
      create_lead: string;
      create_button: string;
      checking_relay: string;
      relay_unreachable: string;
      join_title: string;
      join_lead: string;
      join_button: string;
      join_and_share: string;
      join_share_title: string;
      join_share_body: string;
      join_consent_note: string;
      join_options: string;
      join_viewer: string;
      relay_label: string;
      relay_hint: string;
      team_name_label: string;
      team_name_placeholder: string;
      display_name_label: string;
      display_name_placeholder: string;
      display_name_optional: string;
      display_name_default: string;
      invite_label: string;
      share_consent: string;
      privacy_header: string;
      privacy_body: string;
      hosting_summary: string;
      hosting_header: string;
      hosting_body: string;
      detect_button: string;
      detecting: string;
      detect_hint: string;
      host_button: string;
      host_hint: string;
      host_manage_hint: string;
      host_running: string;
      host_starting: string;
      host_stop: string;
      stopping: string;
      host_ownership_unknown: string;
      detect_ts_ok: string;
      detect_ts_down: string;
      detect_ts_none: string;
      detect_relay_ok: string;
      detect_relay_none: string;
      detect_relay_external: string;
      detect_filled: string;
      detect_filled_unreachable: string;
      detect_filled_local: string;
      detect_filled_pending: string;
      detect_nofill: string;
      tailscale_connect_hint: string;
      copy_cmd: string;
      command_label: string;
      copy_failed: string;
      relay_manage_summary: string;
      relay_manage_body: string;
      member_summary: string;
      role_owner: string;
      role_member: string;
      roster_age: string;
      refresh: string;
      leave: string;
      on_board: string;
      viewing_only: string;
      retraction_pending: string;
      retraction_pending_title: string;
      retraction_pending_body: string;
      retry_retraction: string;
      sharing_needs_attention: string;
      sharing_error_title: string;
      sharing_error_body: string;
      sharing_on_title: string;
      sharing_off_title: string;
      sharing_on: string;
      sharing_off: string;
      share_score: string;
      stop_sharing: string;
      publish_now: string;
      published_age: string;
      manage_summary: string;
      rename: string;
      invite_header: string;
      rotate: string;
      rotate_title: string;
      copy_invite: string;
      copied: string;
      invite_note: string;
      leave_title: string;
      leave_body: string;
      board_empty: string;
      board_label: string;
      col_member: string;
      col_score: string;
      col_unlocked: string;
      col_tier: string;
      col_actions: string;
      owner_badge: string;
      you_badge: string;
      not_shared: string;
      kick: string;
      kick_title: string;
    };
  };

  // ── Kanban ──
  kanban: {
    loading: string;
    loadFailed: string;
    loadFailedHint: string;
    board: string;
    newBoard: string;
    newBoardTitle: string;
    newBoardDescription: string;
    slug: string;
    slugHint: string;
    displayName: string;
    displayNameHint: string;
    description: string;
    descriptionHint: string;
    icon: string;
    iconHint: string;
    switchAfterCreate: string;
    cancel: string;
    creating: string;
    createBoard: string;
    search: string;
    filterCards: string;
    tenant: string;
    allTenants: string;
    assignee: string;
    allProfiles: string;
    showArchived: string;
    lanesByProfile: string;
    nudgeDispatcher: string;
    refresh: string;
    selected: string;
    complete: string;
    archive: string;
    apply: string;
    clear: string;
    createTask: string;
    noTasks: string;
    unassigned: string;
    needsAssignee?: string;
    needsAssigneeHint?: string;
    untitled: string;
    loadingDetail: string;
    addComment: string;
    comment: string;
    status: string;
    workspace: string;
    skills: string;
    createdBy: string;
    result: string;
    comments: string;
    events: string;
    runHistory: string;
    workerLog: string;
    loadingLog: string;
    noWorkerLog: string;
    noDescription: string;
    noComments: string;
    edit: string;
    save: string;
    dependencies: string;
    parents: string;
    children: string;
    none: string;
    addParent: string;
    addChild: string;
    removeDependency: string;
    block: string;
    unblock: string;
    notifyHomeChannels: string;
    diagnostics: string;
    hide: string;
    show: string;
    attention: string;
    tasksNeedAttention: string;
    taskNeedsAttention: string;
    diagnostic: string;
    open: string;
    close: string;
    reassignTo: string;
    copied: string;
    copyCommand: string;
    reclaim: string;
    reassign: string;
    renderingError: string;
    reloadView: string;
    wsAuthFailed: string;
    markDone: string;
    markArchived: string;
    warning: string;
    phantomIds: string;
    active: string;
    ended: string;
    noProfile: string;
    showAllAttempts: string;
    sendingUpdates: string;
    sendNotifications: string;
    archiveBoardConfirm: string;
    archiveBoardTitle: string;
    boardSwitcherHint: string;
    taskCreatedWarning: string;
    moveFailed: string;
    bulkFailed: string;
    completionBlockedHallucination: string;
    suspectedHallucinatedReferences: string;
    pickProfileFirst: string;
    unblockedMessage: string;
    unblockFailed: string;
    reclaimedMessage: string;
    reclaimFailed: string;
    reassignedMessage: string;
    reassignFailed: string;
    selectForBulk: string;
    clickToEdit: string;
    clickToEditAssignee: string;
    emptyAssignee: string;
    columnLabels: {
      triage: string;
      todo: string;
      scheduled: string;
      ready: string;
      running: string;
      blocked: string;
      review?: string;
      done: string;
      archived: string;
    };
    columnHelp: {
      triage: string;
      todo: string;
      scheduled: string;
      ready: string;
      running: string;
      blocked: string;
      review?: string;
      done: string;
      archived: string;
    };
    confirmDone: string;
    confirmArchive: string;
    confirmBlocked: string;
    confirmScheduled?: string;
    completionSummary: string;
    completionSummaryRequired: string;
    triagePlaceholder: string;
    taskTitlePlaceholder: string;
    specifier: string;
    assigneePlaceholder: string;
    priority: string;
    skillsPlaceholder: string;
    noParent: string;
    workspacePathDir: string;
    workspacePathOptional: string;
    logTruncated: string;
    logAt: string;
  };
}
