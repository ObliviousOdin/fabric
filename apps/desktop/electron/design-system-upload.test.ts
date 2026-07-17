import assert from 'node:assert/strict'
import { EventEmitter, once } from 'node:events'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import test from 'node:test'

import { DESIGN_SYSTEM_ZIP_MAX_BYTES, importDesignSystemZipForIpc } from './design-system-upload'

async function listen(server: http.Server): Promise<string> {
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()

  if (!address || typeof address === 'string') {
    throw new Error('test server did not expose a TCP address')
  }

  return `http://127.0.0.1:${address.port}`
}

test('streams a new design ZIP to the captured global-remote profile and returns JSON', async t => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-design-upload-'))
  const sourcePath = path.join(tempDir, 'product-system.zip')
  const archive = Buffer.concat([Buffer.from('PK\u0003\u0004'), Buffer.alloc(256 * 1024, 0x61)])
  fs.writeFileSync(sourcePath, archive)
  t.after(() => fs.rmSync(tempDir, { force: true, recursive: true }))

  let received:
    | {
        body: Buffer
        headers: http.IncomingHttpHeaders
        method?: string
        url?: string
      }
    | undefined
  const server = http.createServer((request, response) => {
    const chunks: Buffer[] = []
    request.on('data', chunk => chunks.push(Buffer.from(chunk)))
    request.on('end', () => {
      received = {
        body: Buffer.concat(chunks),
        headers: request.headers,
        method: request.method,
        url: request.url
      }
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ id: 'system-1', revision: 1 }))
    })
  })
  const baseUrl = await listen(server)
  t.after(() => server.close())

  const result = await importDesignSystemZipForIpc(
    {
      generation: 7,
      name: 'Product system',
      profile: 'research',
      sourcePath,
      // Renderer-supplied transport values must never select the destination or credential.
      baseUrl: 'https://attacker.invalid',
      token: 'renderer-token'
    } as any,
    {
      ensureBackend: async profile => {
        assert.equal(profile, 'research')

        return { authMode: 'token', baseUrl, token: 'main-process-token' }
      },
      globalRemoteActive: () => true,
      profileHasRemoteOverride: () => false,
      timeoutMs: 5_000
    }
  )

  assert.deepEqual(result, { id: 'system-1', revision: 1 })
  assert.equal(received?.method, 'POST')
  assert.equal(received?.url, '/api/design-systems/import?profile=research')
  assert.equal(received?.headers['x-fabric-session-token'], 'main-process-token')
  assert.notEqual(received?.headers['x-fabric-session-token'], 'renderer-token')
  assert.match(String(received?.headers['content-type']), /^multipart\/form-data; boundary=/)
  assert.equal(Number(received?.headers['content-length']), received?.body.length)

  const body = received?.body.toString('latin1') || ''
  assert.match(body, /name="name"\r\n\r\nProduct system\r\n/)
  assert.match(body, /name="generation"\r\n\r\n7\r\n/)
  assert.match(body, /name="file"; filename="product-system\.zip"/)
  assert.equal(received?.body.includes(archive), true)
  assert.equal(body.includes(sourcePath), false)
})

test('uses the OAuth session transport for a replacement without exposing cookie auth to the renderer', async t => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-design-upload-oauth-'))
  const sourcePath = path.join(tempDir, 'replacement.ZIP')
  fs.writeFileSync(sourcePath, Buffer.from('PK\u0003\u0004replacement'))
  t.after(() => fs.rmSync(tempDir, { force: true, recursive: true }))

  const oauthSession = { partition: 'persist:fabric-oauth-test' }
  let requestOptions: any
  const headers: Array<[string, string]> = []
  const written: Buffer[] = []

  class FakeElectronRequest extends EventEmitter {
    setHeader(name: string, value: string) {
      headers.push([name, value])
    }

    write(chunk: Buffer) {
      written.push(Buffer.from(chunk))

      return true
    }

    end() {
      const response = new PassThrough() as PassThrough & {
        headers: Record<string, string>
        statusCode: number
      }
      response.headers = { 'content-type': 'application/json' }
      response.statusCode = 200
      this.emit('response', response)
      response.end(JSON.stringify({ id: 'system/with slash', revision: 4 }))
    }

    abort() {}
  }

  const result = await importDesignSystemZipForIpc(
    {
      generation: 9,
      name: 'Replacement',
      profile: 'remote-profile',
      replaceId: 'system/with slash',
      sourcePath
    },
    {
      electronRequest: options => {
        requestOptions = options

        return new FakeElectronRequest()
      },
      ensureBackend: async () => ({
        authMode: 'oauth',
        baseUrl: 'https://fabric.example',
        token: 'must-not-be-sent'
      }),
      getOauthSession: () => oauthSession,
      globalRemoteActive: () => true,
      profileHasRemoteOverride: () => true,
      timeoutMs: 5_000
    }
  )

  assert.deepEqual(result, { id: 'system/with slash', revision: 4 })
  assert.deepEqual(requestOptions, {
    method: 'POST',
    redirect: 'follow',
    session: oauthSession,
    url: 'https://fabric.example/api/design-systems/system%2Fwith%20slash/revisions',
    useSessionCookies: true
  })
  assert.equal(
    headers.some(([name]) => name.toLowerCase() === 'content-length'),
    false
  )
  assert.equal(
    headers.some(([name]) => name.toLowerCase() === 'x-fabric-session-token'),
    false
  )
  assert.match(headers.find(([name]) => name.toLowerCase() === 'content-type')?.[1] || '', /^multipart\/form-data;/)
  assert.match(Buffer.concat(written).toString('utf8'), /name="generation"\r\n\r\n9\r\n/)
})

test('rejects non-ZIP, sensitive symlink, and oversized sources before resolving a backend', async t => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-design-upload-invalid-'))
  t.after(() => fs.rmSync(tempDir, { force: true, recursive: true }))

  const wrongExtension = path.join(tempDir, 'not-an-archive.txt')
  fs.writeFileSync(wrongExtension, 'not a zip')
  const oversized = path.join(tempDir, 'oversized.zip')
  fs.writeFileSync(oversized, '')
  fs.truncateSync(oversized, DESIGN_SYSTEM_ZIP_MAX_BYTES + 1)
  const sensitive = path.join(tempDir, '.env')
  fs.writeFileSync(sensitive, 'TOKEN=secret')
  const sensitiveLink = path.join(tempDir, 'secret.zip')
  fs.symlinkSync(sensitive, sensitiveLink)

  let backendCalls = 0
  const deps = {
    ensureBackend: async () => {
      backendCalls += 1
      throw new Error('must not resolve')
    },
    globalRemoteActive: () => false,
    profileHasRemoteOverride: () => false
  }
  const requestFor = sourcePath => ({ generation: 1, name: 'System', sourcePath })

  await assert.rejects(importDesignSystemZipForIpc(requestFor(wrongExtension), deps), (error: any) => {
    assert.equal(error.code, 'invalid-extension')

    return true
  })
  await assert.rejects(importDesignSystemZipForIpc(requestFor(oversized), deps), (error: any) => {
    assert.equal(error.code, 'EFBIG')

    return true
  })
  await assert.rejects(importDesignSystemZipForIpc(requestFor(sensitiveLink), deps), (error: any) => {
    assert.equal(error.code, 'sensitive-file')

    return true
  })
  assert.equal(backendCalls, 0)
})

test('fstats the opened descriptor and refuses it when it is no longer a regular file', async () => {
  const input = path.resolve('virtual-design.zip')
  let closed = false
  let opened = false
  const preOpenStat = {
    dev: 1,
    ino: 2,
    isDirectory: () => false,
    isFile: () => true,
    size: 4
  }
  const fsImpl = {
    promises: {
      access: async () => {},
      open: async () => {
        opened = true

        return {
          close: async () => {
            closed = true
          },
          stat: async () => ({ ...preOpenStat, isFile: () => false })
        }
      },
      realpath: async () => input,
      stat: async () => preOpenStat
    }
  }

  await assert.rejects(
    importDesignSystemZipForIpc(
      { generation: 1, name: 'System', sourcePath: input },
      {
        ensureBackend: async () => {
          throw new Error('must not resolve')
        },
        fs: fsImpl,
        globalRemoteActive: () => false,
        profileHasRemoteOverride: () => false
      }
    ),
    (error: any) => {
      assert.equal(error.code, 'invalid-file')

      return true
    }
  )
  assert.equal(opened, true)
  assert.equal(closed, true)
})

test('does not expose the backend destination, credential, or response body in upload errors', async t => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-design-upload-error-'))
  const sourcePath = path.join(tempDir, 'system.zip')
  fs.writeFileSync(sourcePath, Buffer.from('PK\u0003\u0004error'))
  t.after(() => fs.rmSync(tempDir, { force: true, recursive: true }))

  const server = http.createServer((_request, response) => {
    response.writeHead(422, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ detail: 'destination=/srv/private token=main-process-token' }))
  })
  const baseUrl = await listen(server)
  t.after(() => server.close())

  await assert.rejects(
    importDesignSystemZipForIpc(
      { generation: 1, name: 'System', sourcePath },
      {
        ensureBackend: async () => ({ authMode: 'token', baseUrl, token: 'main-process-token' }),
        globalRemoteActive: () => false,
        profileHasRemoteOverride: () => false,
        timeoutMs: 5_000
      }
    ),
    (error: any) => {
      assert.equal(error.code, 'upload-rejected')
      assert.equal(error.statusCode, 422)
      assert.match(error.message, /Fabric/)
      assert.equal(error.message.includes(baseUrl), false)
      assert.equal(error.message.includes('/srv/private'), false)
      assert.equal(error.message.includes('main-process-token'), false)

      return true
    }
  )
})

test('captures profile, name, replacement ID, and generation before asynchronous backend resolution', async t => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-design-upload-capture-'))
  const sourcePath = path.join(tempDir, 'system.zip')
  fs.writeFileSync(sourcePath, Buffer.from('PK\u0003\u0004capture'))
  t.after(() => fs.rmSync(tempDir, { force: true, recursive: true }))

  let releaseBackend: (connection: any) => void = () => {}
  let markBackendStarted: () => void = () => {}
  const backendStarted = new Promise<void>(resolve => {
    markBackendStarted = resolve
  })
  const backend = new Promise<any>(resolve => {
    releaseBackend = resolve
  })
  const written: Buffer[] = []
  let requestedUrl = ''

  class FakeTokenRequest extends EventEmitter {
    write(chunk: Buffer) {
      written.push(Buffer.from(chunk))

      return true
    }

    end() {
      const response = new PassThrough() as PassThrough & { statusCode: number }
      response.statusCode = 200
      this.emit('response', response)
      response.end('{"ok":true}')
    }

    destroy() {}
  }

  const request = {
    generation: 3,
    name: 'Captured name',
    profile: 'captured-profile',
    replaceId: 'captured-id',
    sourcePath
  }
  const resultPromise = importDesignSystemZipForIpc(request, {
    ensureBackend: async profile => {
      assert.equal(profile, 'captured-profile')
      markBackendStarted()

      return backend
    },
    globalRemoteActive: () => true,
    httpRequest: (url: URL) => {
      requestedUrl = url.toString()

      return new FakeTokenRequest()
    },
    profileHasRemoteOverride: () => false,
    timeoutMs: 5_000
  })

  await backendStarted
  request.generation = 99
  request.name = 'Mutated name'
  request.profile = 'mutated-profile'
  request.replaceId = 'mutated-id'
  releaseBackend({ authMode: 'token', baseUrl: 'http://fabric.internal', token: 'internal-token' })

  assert.deepEqual(await resultPromise, { ok: true })
  assert.equal(requestedUrl, 'http://fabric.internal/api/design-systems/captured-id/revisions?profile=captured-profile')
  const body = Buffer.concat(written).toString('utf8')
  assert.match(body, /name="name"\r\n\r\nCaptured name\r\n/)
  assert.match(body, /name="generation"\r\n\r\n3\r\n/)
  assert.equal(body.includes('Mutated name'), false)
})
