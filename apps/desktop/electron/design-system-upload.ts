import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import https from 'node:https'
import path from 'node:path'

import { pathWithGlobalRemoteProfile } from './connection-config'
import { resolveReadableFileForIpc } from './hardening'

const DESIGN_SYSTEM_ZIP_MAX_BYTES = 50 * 1024 * 1024
const DESIGN_SYSTEM_UPLOAD_TIMEOUT_MS = 120_000
const DESIGN_SYSTEM_RESPONSE_MAX_BYTES = 1024 * 1024
const FILE_READ_CHUNK_BYTES = 64 * 1024

function uploadError(code: string, message: string, statusCode?: number) {
  const error = new Error(message) as Error & { code: string; statusCode?: number }
  error.code = code

  if (statusCode !== undefined) {
    error.statusCode = statusCode
  }

  return error
}

function captureUploadRequest(request: any = {}) {
  const sourcePath = typeof request.sourcePath === 'string' ? request.sourcePath : request.sourcePath
  const profile = typeof request.profile === 'string' ? request.profile.trim() || null : null
  const name = typeof request.name === 'string' ? request.name.trim() : ''
  const replaceId = typeof request.replaceId === 'string' ? request.replaceId.trim() || null : null
  const generation = Number(request.generation)

  if (!name) {
    throw uploadError('invalid-name', 'Fabric design-system import requires a name.')
  }

  if (name.length > 120) {
    throw uploadError('invalid-name', 'Fabric design-system names must be 120 characters or fewer.')
  }

  if (!Number.isSafeInteger(generation) || generation < 0) {
    throw uploadError('invalid-generation', 'Fabric design-system import requires a valid generation.')
  }

  if (replaceId && replaceId.length > 200) {
    throw uploadError('invalid-replace-id', 'Fabric design-system replacement ID is too long.')
  }

  return { generation, name, profile, replaceId, sourcePath }
}

function importPath(replaceId: null | string) {
  return replaceId ? `/api/design-systems/${encodeURIComponent(replaceId)}/revisions` : '/api/design-systems/import'
}

function multipartBuffers(name: string, generation: number, boundary: string, filename: string) {
  const safeFilename = filename.replace(/[^\x20-\x7e]|["\\]/g, '_').slice(0, 255) || 'design-system.zip'
  const prefix = Buffer.from(
    `--${boundary}\r\n` +
      'Content-Disposition: form-data; name="name"\r\n\r\n' +
      `${name}\r\n` +
      `--${boundary}\r\n` +
      'Content-Disposition: form-data; name="generation"\r\n\r\n' +
      `${generation}\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="${safeFilename}"\r\n` +
      'Content-Type: application/zip\r\n\r\n',
    'utf8'
  )
  const suffix = Buffer.from(`\r\n--${boundary}--\r\n`, 'utf8')

  return { prefix, suffix }
}

async function writeChunk(request, chunk: Buffer, signal: AbortSignal) {
  if (signal.aborted) {
    throw uploadError('upload-aborted', 'Fabric design-system import was interrupted.')
  }

  if (request.write(chunk) !== false) {
    return
  }

  await new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      request.removeListener('drain', onDrain)
      request.removeListener('error', onError)
      signal.removeEventListener('abort', onAbort)
    }
    const onDrain = () => {
      cleanup()
      resolve()
    }
    const onError = () => {
      cleanup()
      reject(uploadError('upload-failed', 'Could not import the design system into Fabric.'))
    }
    const onAbort = () => {
      cleanup()
      reject(uploadError('upload-aborted', 'Fabric design-system import was interrupted.'))
    }

    request.once('drain', onDrain)
    request.once('error', onError)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

async function streamOpenedFile(
  request,
  fileHandle,
  size: number,
  prefix: Buffer,
  suffix: Buffer,
  signal: AbortSignal
) {
  await writeChunk(request, prefix, signal)

  let position = 0

  while (position < size) {
    const length = Math.min(FILE_READ_CHUNK_BYTES, size - position)
    const buffer = Buffer.allocUnsafe(length)
    const { bytesRead } = await fileHandle.read(buffer, 0, length, position)

    if (bytesRead <= 0) {
      throw uploadError('source-changed', 'The selected design-system ZIP changed while Fabric was importing it.')
    }

    await writeChunk(request, bytesRead === buffer.length ? buffer : buffer.subarray(0, bytesRead), signal)
    position += bytesRead
  }

  await writeChunk(request, suffix, signal)
  request.end()
}

function responseJson(request, timeoutMs: number, abortController: AbortController) {
  let timer: NodeJS.Timeout | undefined

  const promise = new Promise((resolve, reject) => {
    const fail = (error: Error) => {
      if (timer) {
        clearTimeout(timer)
      }
      abortController.abort()
      reject(error)
    }

    request.once('response', response => {
      const chunks: Buffer[] = []
      let byteCount = 0

      response.on('error', () => fail(uploadError('upload-failed', 'Could not read the response from Fabric.')))
      response.on('data', chunk => {
        const buffer = Buffer.from(chunk)
        byteCount += buffer.length

        if (byteCount > DESIGN_SYSTEM_RESPONSE_MAX_BYTES) {
          try {
            response.destroy()
          } catch {
            // Already closed.
          }
          fail(uploadError('response-too-large', 'Fabric returned an unexpectedly large design-system response.'))

          return
        }

        chunks.push(buffer)
      })
      response.on('end', () => {
        if (timer) {
          clearTimeout(timer)
        }

        const statusCode = response.statusCode || 500

        if (statusCode >= 400) {
          fail(
            uploadError(
              'upload-rejected',
              `Fabric rejected the design-system import (status ${statusCode}).`,
              statusCode
            )
          )

          return
        }

        const text = Buffer.concat(chunks).toString('utf8')

        if (!text) {
          fail(uploadError('invalid-response', 'Fabric returned an empty design-system import response.'))

          return
        }

        try {
          resolve(JSON.parse(text))
        } catch {
          fail(uploadError('invalid-response', 'Fabric returned an invalid design-system import response.'))
        }
      })
    })
    request.once('error', () => fail(uploadError('upload-failed', 'Could not import the design system into Fabric.')))

    timer = setTimeout(() => {
      abortController.abort()

      try {
        if (typeof request.destroy === 'function') {
          request.destroy()
        } else if (typeof request.abort === 'function') {
          request.abort()
        }
      } catch {
        // Already closed.
      }

      reject(uploadError('upload-timeout', `Fabric design-system import timed out after ${timeoutMs}ms.`))
    }, timeoutMs)
  })

  // The transport can fail while the file pump is awaiting I/O. Attach a
  // handler immediately so Node never reports the response promise as unhandled.
  void promise.catch(() => {})

  return promise
}

function createOauthRequest(url: string, contentType: string, deps: any) {
  const oauthSession = deps.getOauthSession?.()

  if (!oauthSession || typeof deps.electronRequest !== 'function') {
    throw uploadError('oauth-unavailable', 'Fabric OAuth design-system import transport is unavailable.')
  }

  const request = deps.electronRequest({
    method: 'POST',
    redirect: 'follow',
    session: oauthSession,
    url,
    useSessionCookies: true
  })
  request.setHeader('Content-Type', contentType)

  return request
}

function createTokenRequest(url: string, token: string, contentType: string, contentLength: number, deps: any) {
  let parsed: URL

  try {
    parsed = new URL(url)
  } catch {
    throw uploadError('invalid-destination', 'Fabric selected an invalid design-system import destination.')
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw uploadError('invalid-destination', 'Fabric selected an unsupported design-system import destination.')
  }

  const requestImpl =
    parsed.protocol === 'https:' ? deps.httpsRequest || https.request : deps.httpRequest || http.request

  return requestImpl(parsed, {
    headers: {
      'Content-Length': String(contentLength),
      'Content-Type': contentType,
      'X-Fabric-Session-Token': token
    },
    method: 'POST'
  })
}

async function openDesignSystemZip(sourcePath, deps: any) {
  const fsImpl = deps.fs || fs
  const resolved = await resolveReadableFileForIpc(sourcePath, {
    fs: fsImpl,
    maxBytes: DESIGN_SYSTEM_ZIP_MAX_BYTES,
    purpose: 'Fabric design-system import'
  })

  if (path.extname(resolved.realPath).toLowerCase() !== '.zip') {
    throw uploadError('invalid-extension', 'Fabric design-system import accepts only .zip files.')
  }

  let fileHandle

  try {
    fileHandle = await fsImpl.promises.open(resolved.realPath, 'r')
  } catch {
    throw uploadError('open-failed', 'Fabric could not open the selected design-system ZIP.')
  }

  try {
    const stat = await fileHandle.stat()

    if (!stat.isFile()) {
      throw uploadError('invalid-file', 'Fabric design-system import accepts only regular .zip files.')
    }

    if (stat.size > DESIGN_SYSTEM_ZIP_MAX_BYTES) {
      throw uploadError(
        'EFBIG',
        `Fabric design-system import failed: file is too large (${stat.size} bytes; limit ${DESIGN_SYSTEM_ZIP_MAX_BYTES} bytes).`
      )
    }

    if (
      Number.isFinite(resolved.stat.dev) &&
      Number.isFinite(resolved.stat.ino) &&
      (stat.dev !== resolved.stat.dev || stat.ino !== resolved.stat.ino)
    ) {
      throw uploadError('source-changed', 'The selected design-system ZIP changed before Fabric could import it.')
    }

    return { fileHandle, size: stat.size }
  } catch (error) {
    await fileHandle.close().catch(() => {})
    throw error
  }
}

async function importDesignSystemZipForIpc(rawRequest: any, deps: any) {
  // Capture every renderer-controlled routing/value field before the first
  // await. Later UI changes cannot redirect or relabel an in-flight import.
  const request = captureUploadRequest(rawRequest)
  const opened = await openDesignSystemZip(request.sourcePath, deps)

  try {
    const connection = await deps.ensureBackend(request.profile)
    const requestPath = pathWithGlobalRemoteProfile(importPath(request.replaceId), request.profile, {
      globalRemote: Boolean(deps.globalRemoteActive()),
      profileRemoteOverride: Boolean(deps.profileHasRemoteOverride(request.profile))
    })
    const url = `${connection.baseUrl}${requestPath}`
    const boundary = deps.boundary || `fabric-design-${crypto.randomBytes(18).toString('hex')}`
    const { prefix, suffix } = multipartBuffers(
      request.name,
      request.generation,
      boundary,
      path.basename(request.sourcePath)
    )
    const contentType = `multipart/form-data; boundary=${boundary}`
    const contentLength = prefix.length + opened.size + suffix.length
    const timeoutMs = deps.timeoutMs || DESIGN_SYSTEM_UPLOAD_TIMEOUT_MS

    const transport =
      connection.authMode === 'oauth'
        ? createOauthRequest(url, contentType, deps)
        : createTokenRequest(url, connection.token, contentType, contentLength, deps)
    const abortController = new AbortController()
    const resultPromise = responseJson(transport, timeoutMs, abortController)

    try {
      await streamOpenedFile(transport, opened.fileHandle, opened.size, prefix, suffix, abortController.signal)
    } catch (error) {
      abortController.abort()

      try {
        transport.destroy?.()
      } catch {
        // Already closed.
      }

      throw error
    }

    return await resultPromise
  } finally {
    await opened.fileHandle.close().catch(() => {})
  }
}

export { DESIGN_SYSTEM_UPLOAD_TIMEOUT_MS, DESIGN_SYSTEM_ZIP_MAX_BYTES, importDesignSystemZipForIpc }
