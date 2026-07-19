import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('fabricDesktop', {
  getConnection: profile => ipcRenderer.invoke('fabric:connection', profile),
  revalidateConnection: () => ipcRenderer.invoke('fabric:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('fabric:backend:touch', profile),
  getGatewayWsUrl: profile => ipcRenderer.invoke('fabric:gateway:ws-url', profile),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('fabric:window:openSession', sessionId, opts),
  openNewSessionWindow: () => ipcRenderer.invoke('fabric:window:openNewSession'),
  liveView: {
    open: request => ipcRenderer.invoke('fabric:live-view:open', request),
    close: sessionId => ipcRenderer.invoke('fabric:live-view:close', sessionId),
    pushState: payload => ipcRenderer.send('fabric:live-view:state', payload),
    control: payload => ipcRenderer.send('fabric:live-view:control', payload),
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fabric:live-view:state', listener)

      return () => ipcRenderer.removeListener('fabric:live-view:state', listener)
    },
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fabric:live-view:control', listener)

      return () => ipcRenderer.removeListener('fabric:live-view:control', listener)
    }
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('fabric:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('fabric:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('fabric:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('fabric:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('fabric:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('fabric:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('fabric:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fabric:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('fabric:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fabric:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('fabric:pet-overlay:control', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('fabric:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('fabric:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('fabric:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('fabric:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('fabric:connection-config:test', payload),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('fabric:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('fabric:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('fabric:connection-config:oauth-logout', remoteUrl),
  profile: {
    get: () => ipcRenderer.invoke('fabric:profile:get'),
    set: name => ipcRenderer.invoke('fabric:profile:set', name)
  },
  api: request => ipcRenderer.invoke('fabric:api', request),
  importDesignSystemZip: request => ipcRenderer.invoke('fabric:design-system:import', request),
  notify: payload => ipcRenderer.invoke('fabric:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('fabric:requestMicrophoneAccess'),
  readFileDataUrl: filePath => ipcRenderer.invoke('fabric:readFileDataUrl', filePath),
  readFileText: filePath => ipcRenderer.invoke('fabric:readFileText', filePath),
  selectPaths: options => ipcRenderer.invoke('fabric:selectPaths', options),
  writeClipboard: text => ipcRenderer.invoke('fabric:writeClipboard', text),
  saveImageFromUrl: url => ipcRenderer.invoke('fabric:saveImageFromUrl', url),
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('fabric:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('fabric:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('fabric:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('fabric:watchPreviewFile', url),
  stopPreviewFileWatch: id => ipcRenderer.invoke('fabric:stopPreviewFileWatch', id),
  setTitleBarTheme: payload => ipcRenderer.send('fabric:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('fabric:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('fabric:translucency', payload),
  setPreviewShortcutActive: active => ipcRenderer.send('fabric:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('fabric:openExternal', url),
  openPreviewInBrowser: url => ipcRenderer.invoke('fabric:openPreviewInBrowser', url),
  fetchLinkTitle: url => ipcRenderer.invoke('fabric:fetchLinkTitle', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('fabric:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('fabric:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('fabric:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('fabric:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('fabric:zoom:get'),
    setPercent: percent => ipcRenderer.send('fabric:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fabric:zoom:changed', listener)

      return () => ipcRenderer.removeListener('fabric:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('fabric:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('fabric:logs:recent'),
  readDir: dirPath => ipcRenderer.invoke('fabric:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('fabric:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('fabric:fs:reveal', targetPath),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('fabric:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('fabric:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('fabric:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('fabric:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('fabric:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('fabric:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('fabric:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('fabric:git:branchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('fabric:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('fabric:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('fabric:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('fabric:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('fabric:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('fabric:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('fabric:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('fabric:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('fabric:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('fabric:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('fabric:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('fabric:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('fabric:git:review:shipInfo', repoPath),
      createPr: repoPath => ipcRenderer.invoke('fabric:git:review:createPr', repoPath)
    }
  },
  terminal: {
    dispose: id => ipcRenderer.invoke('fabric:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('fabric:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('fabric:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('fabric:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `fabric:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `fabric:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('fabric:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('fabric:close-preview-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('fabric:open-updates', listener)

    return () => ipcRenderer.removeListener('fabric:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fabric:deep-link', listener)

    return () => ipcRenderer.removeListener('fabric:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('fabric:deep-link-ready'),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fabric:window-state-changed', listener)

    return () => ipcRenderer.removeListener('fabric:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('fabric:focus-session', listener)

    return () => ipcRenderer.removeListener('fabric:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fabric:notification-action', listener)

    return () => ipcRenderer.removeListener('fabric:notification-action', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fabric:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('fabric:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fabric:backend-exit', listener)

    return () => ipcRenderer.removeListener('fabric:backend-exit', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('fabric:power-resume', listener)

    return () => ipcRenderer.removeListener('fabric:power-resume', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fabric:boot-progress', listener)

    return () => ipcRenderer.removeListener('fabric:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('fabric:bootstrap:get'),
  resetBootstrap: () => ipcRenderer.invoke('fabric:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('fabric:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('fabric:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('fabric:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('fabric:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('fabric:version'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('fabric:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('fabric:uninstall:summary'),
    run: mode => ipcRenderer.invoke('fabric:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('fabric:updates:check'),
    apply: opts => ipcRenderer.invoke('fabric:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('fabric:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('fabric:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('fabric:updates:progress', listener)

      return () => ipcRenderer.removeListener('fabric:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('fabric:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('fabric:vscode-theme:search', query)
  }
})
