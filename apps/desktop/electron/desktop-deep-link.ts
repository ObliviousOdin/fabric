function normalizeDesktopProtocolSchemes(schemes) {
  return new Set(
    (Array.isArray(schemes) ? schemes : [])
      .filter(scheme => typeof scheme === 'string')
      .map(scheme => scheme.trim().toLowerCase())
      .filter(Boolean)
  )
}

function parseDesktopDeepLink(rawUrl, schemes) {
  if (typeof rawUrl !== 'string' || !rawUrl.trim()) {
    return null
  }
  const allowed = normalizeDesktopProtocolSchemes(schemes)
  let parsed

  try {
    parsed = new URL(rawUrl)
  } catch {
    return null
  }

  const scheme = parsed.protocol.slice(0, -1).toLowerCase()
  if (!allowed.has(scheme)) {
    return null
  }

  try {
    const params = {}
    parsed.searchParams.forEach((value, key) => {
      params[key] = value
    })

    return {
      scheme,
      kind: parsed.hostname || '',
      name: decodeURIComponent((parsed.pathname || '').replace(/^\//, '')),
      params
    }
  } catch {
    return null
  }
}

function extractDesktopDeepLink(argv, schemes) {
  if (!Array.isArray(argv)) {
    return null
  }

  for (const arg of argv) {
    if (parseDesktopDeepLink(arg, schemes)) {
      return arg
    }
  }

  return null
}

export { extractDesktopDeepLink, normalizeDesktopProtocolSchemes, parseDesktopDeepLink }
