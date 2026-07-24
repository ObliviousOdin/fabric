import initFabricLinkCore, {
  fabric_link_ciphersuite,
  fabric_link_protocol_version,
  fabric_link_wasm_controller_decrypt,
  fabric_link_wasm_controller_encrypt,
  fabric_link_wasm_controller_join,
  fabric_link_wasm_controller_key_package,
  fabric_link_wasm_create_controller,
  fabric_link_wasm_create_pair,
  fabric_link_wasm_host_encrypt,
  fabric_link_wasm_host_decrypt,
} from '/wasm/fabric_link_core.js'

const DB_NAME = 'fabric-link-phase0'
const STORE_NAME = 'encrypted-link-state'
const WRAPPING_KEY_ID = 'device-wrapping-key'
const STATE_ID = 'mls-state-v1'

function stateAad(controllerId) {
  return new TextEncoder().encode(`fabric-link-web-controller-state-v1\0${controllerId}`)
}

function hexBytes(value) {
  if (value.length % 2 !== 0) throw new Error('invalid corpus hex')
  return Uint8Array.from(value.match(/.{2}/g) || [], byte => Number.parseInt(byte, 16))
}

function bytesHex(value) {
  return Array.from(value, byte => byte.toString(16).padStart(2, '0')).join('')
}

function concatBytes(...values) {
  const result = new Uint8Array(values.reduce((length, value) => length + value.length, 0))
  let offset = 0
  for (const value of values) {
    result.set(value, offset)
    offset += value.length
  }
  return result
}

async function sha256(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', value))
}

async function deriveEnrollmentKey(corpus, direction) {
  const secret = hexBytes(corpus.pairing_secret_hex)
  const salt = await sha256(
    concatBytes(hexBytes(corpus.pairing_route_hex), hexBytes(corpus.pairing_handle_hex)),
  )
  const inputKey = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveBits'])
  const bits = await crypto.subtle.deriveBits(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt,
      info: new TextEncoder().encode(`fabric-link-enrollment-${direction}-key-v3`),
    },
    inputKey,
    256,
  )
  return new Uint8Array(bits)
}

async function verifyAesKnownAnswer(corpus, direction, plaintextKey) {
  const keyBytes = await deriveEnrollmentKey(corpus, direction)
  if (bytesHex(keyBytes) !== corpus[`enrollment_${direction}_key_hex`]) {
    throw new Error(`${direction} enrollment HKDF known answer differs`)
  }
  const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'AES-GCM' }, false, [
    'decrypt',
  ])
  const plaintext = new Uint8Array(
    await crypto.subtle.decrypt(
      {
        name: 'AES-GCM',
        iv: hexBytes(corpus[`enrollment_${direction}_nonce_hex`]),
        additionalData: hexBytes(corpus[`enrollment_${direction}_aad_hex`]),
        tagLength: 128,
      },
      key,
      hexBytes(corpus[`enrollment_${direction}_ciphertext_hex`]),
    ),
  )
  if (bytesHex(plaintext) !== corpus[plaintextKey]) {
    throw new Error(`${direction} enrollment AES-GCM known answer differs`)
  }
}

async function verifyInteropCorpus() {
  const response = await fetch('/fixtures/v3-interoperability.json', {
    cache: 'no-store',
  })
  if (!response.ok) throw new Error('v3 interoperability corpus is unavailable')
  const corpus = await response.json()
  if (corpus.schema_version !== 1 || corpus.protocol_version !== 3) {
    throw new Error('unsupported interoperability corpus')
  }
  for (const [valueKey, digestKey] of [
    ['pairing_cbor_hex', 'pairing_cbor_sha256_hex'],
    ['link_request_cbor_hex', 'link_request_sha256_hex'],
    ['enrollment_request_cbor_hex', 'enrollment_request_sha256_hex'],
  ]) {
    const digest = await sha256(hexBytes(corpus[valueKey]))
    if (bytesHex(digest) !== corpus[digestKey]) {
      throw new Error(`${valueKey} SHA-256 known answer differs`)
    }
  }
  const pairingDigest = await sha256(hexBytes(corpus.pairing_cbor_hex))
  for (const [direction, domain] of [
    ['request', 'fabric-link-enrollment-request-aad-v3'],
    ['response', 'fabric-link-enrollment-response-aad-v3'],
  ]) {
    const expectedAad = concatBytes(
      new TextEncoder().encode(domain),
      new Uint8Array([0]),
      pairingDigest,
    )
    if (bytesHex(expectedAad) !== corpus[`enrollment_${direction}_aad_hex`]) {
      throw new Error(`${direction} enrollment AAD known answer differs`)
    }
  }
  await verifyAesKnownAnswer(corpus, 'request', 'enrollment_request_cbor_hex')
  await verifyAesKnownAnswer(corpus, 'response', 'enrollment_response_plaintext_cbor_hex')
}

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.addEventListener('success', () => resolve(request.result), { once: true })
    request.addEventListener('error', () => reject(request.error), { once: true })
  })
}

function transactionComplete(transaction) {
  return new Promise((resolve, reject) => {
    transaction.addEventListener('complete', resolve, { once: true })
    transaction.addEventListener('abort', () => reject(transaction.error), { once: true })
    transaction.addEventListener('error', () => reject(transaction.error), { once: true })
  })
}

async function deleteDatabase() {
  await requestResult(indexedDB.deleteDatabase(DB_NAME))
}

async function openDatabase() {
  const request = indexedDB.open(DB_NAME, 1)
  request.addEventListener('upgradeneeded', () => {
    request.result.createObjectStore(STORE_NAME)
  })
  return requestResult(request)
}

async function putRecord(database, key, value) {
  const transaction = database.transaction(STORE_NAME, 'readwrite')
  const completed = transactionComplete(transaction)
  transaction.objectStore(STORE_NAME).put(value, key)
  await completed
}

async function getRecord(database, key) {
  const transaction = database.transaction(STORE_NAME, 'readonly')
  const completed = transactionComplete(transaction)
  const value = await requestResult(transaction.objectStore(STORE_NAME).get(key))
  await completed
  return value
}

async function expectExportRejected(key) {
  try {
    await crypto.subtle.exportKey('raw', key)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'InvalidAccessError') return
    throw error
  }
  throw new Error('non-extractable wrapping key was exportable')
}

async function run() {
  if (!window.isSecureContext) throw new Error('browser harness requires a secure context')
  if (!crypto?.subtle) throw new Error('WebCrypto SubtleCrypto is unavailable')
  if (!indexedDB) throw new Error('IndexedDB is unavailable')

  await verifyInteropCorpus()
  await initFabricLinkCore('/wasm/fabric_link_core_bg.wasm')
  if (fabric_link_protocol_version() !== 3) {
    throw new Error('browser WASM protocol version does not match native bindings')
  }
  if (!fabric_link_ciphersuite().includes('DHKEMX25519')) {
    throw new Error('browser WASM ciphersuite metadata is missing')
  }

  localStorage.clear()
  await deleteDatabase()
  let database = await openDatabase()
  const wrappingKey = await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
  if (wrappingKey.extractable) throw new Error('wrapping key must be non-extractable')
  await expectExportRejected(wrappingKey)

  const identity = new TextEncoder().encode('phase0-browser-controller')
  const initialControllerState = fabric_link_wasm_create_controller(identity)
  const originalKeyPackage = fabric_link_wasm_controller_key_package(initialControllerState)
  if (!(initialControllerState instanceof Uint8Array) || initialControllerState.length < 64) {
    throw new Error('browser WASM did not create opaque controller state')
  }
  if (!(originalKeyPackage instanceof Uint8Array) || originalKeyPackage.length < 64) {
    throw new Error('browser WASM did not create an MLS KeyPackage')
  }
  if (new TextDecoder().decode(initialControllerState.slice(0, 8)) !== 'FLNKST01') {
    throw new Error('browser WASM returned an unknown protocol-state format')
  }
  const pair = fabric_link_wasm_create_pair(
    new TextEncoder().encode('phase0-browser-host'),
    new TextEncoder().encode('phase0-browser-pair'),
    originalKeyPackage,
  )
  let hostState = pair.host_state()
  let controllerState = fabric_link_wasm_controller_join(
    initialControllerState,
    pair.welcome(),
  )
  pair.free()
  const firstPlaintext = new TextEncoder().encode('first browser record')
  const firstEncrypted = fabric_link_wasm_host_encrypt(hostState, firstPlaintext)
  hostState = firstEncrypted.opaque_state()
  const firstDecrypted = fabric_link_wasm_controller_decrypt(
    controllerState,
    firstEncrypted.message(),
  )
  controllerState = firstDecrypted.opaque_state()
  if (new TextDecoder().decode(firstDecrypted.plaintext()) !== 'first browser record') {
    throw new Error('browser WASM did not complete an MLS pair/decrypt flow')
  }
  firstEncrypted.free()
  firstDecrypted.free()

  const controllerPlaintext = new TextEncoder().encode('controller browser record')
  const controllerEncrypted = fabric_link_wasm_controller_encrypt(
    controllerState,
    controllerPlaintext,
  )
  controllerState = controllerEncrypted.opaque_state()
  const controllerDecrypted = fabric_link_wasm_host_decrypt(
    hostState,
    controllerEncrypted.message(),
  )
  hostState = controllerDecrypted.opaque_state()
  if (new TextDecoder().decode(controllerDecrypted.plaintext()) !== 'controller browser record') {
    throw new Error('browser WASM did not complete a controller-to-host MLS flow')
  }
  controllerEncrypted.free()
  controllerDecrypted.free()

  const controllerId = 'phase0-browser-controller'
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: stateAad(controllerId) },
    wrappingKey,
    controllerState,
  )
  await putRecord(database, WRAPPING_KEY_ID, wrappingKey)
  await putRecord(database, STATE_ID, {
    ciphertext,
    controllerId,
    iv,
    version: 1,
  })
  database.close()

  database = await openDatabase()
  const restoredKey = await getRecord(database, WRAPPING_KEY_ID)
  const restoredState = await getRecord(database, STATE_ID)
  if (!(restoredKey instanceof CryptoKey)) throw new Error('CryptoKey did not survive IndexedDB')
  if (restoredKey.extractable) throw new Error('restored wrapping key became extractable')
  if (restoredState?.version !== 1) throw new Error('encrypted state version is missing')
  if (!restoredState?.ciphertext || !restoredState?.iv) {
    throw new Error('encrypted state envelope is incomplete')
  }
  if ('plaintext' in restoredState || 'keyPackage' in restoredState || 'opaqueState' in restoredState) {
    throw new Error('plaintext protocol state escaped the ciphertext envelope')
  }
  if (restoredState.controllerId !== controllerId) {
    throw new Error('encrypted state envelope is not bound to its controller')
  }

  const restoredPlaintext = new Uint8Array(
    await crypto.subtle.decrypt(
      {
        name: 'AES-GCM',
        iv: restoredState.iv,
        additionalData: stateAad(restoredState.controllerId),
      },
      restoredKey,
      restoredState.ciphertext,
    ),
  )
  const secondPlaintext = new TextEncoder().encode('second browser record')
  const secondEncrypted = fabric_link_wasm_host_encrypt(hostState, secondPlaintext)
  const secondDecrypted = fabric_link_wasm_controller_decrypt(
    restoredPlaintext,
    secondEncrypted.message(),
  )
  if (new TextDecoder().decode(secondDecrypted.plaintext()) !== 'second browser record') {
    throw new Error('restored browser protocol state could not decrypt its next MLS record')
  }
  secondEncrypted.free()
  secondDecrypted.free()
  if (localStorage.length !== 0) throw new Error('Link data must not use localStorage')

  database.close()
  const clearResponse = await fetch('/clear', { cache: 'no-store' })
  if (!clearResponse.ok) throw new Error('Clear-Site-Data endpoint failed')
  await new Promise(resolve => setTimeout(resolve, 50))
  database = await openDatabase()
  if ((await getRecord(database, WRAPPING_KEY_ID)) !== undefined) {
    throw new Error('clear-site-data simulation retained the wrapping key')
  }
  if ((await getRecord(database, STATE_ID)) !== undefined) {
    throw new Error('clear-site-data simulation retained encrypted Link state')
  }
  database.close()
  await deleteDatabase()

  return {
    clearSiteDataRemovedAccess: true,
    encryptedStateRoundTrip: true,
    indexedDbCryptoKeyPersistence: true,
    interoperabilityCorpus: true,
    localStorageEntries: localStorage.length,
    nonExtractable: true,
    wasmBidirectionalApplicationFlow: true,
    wasmPairDecryptPersistence: true,
    wasmProtocolVersion: fabric_link_protocol_version(),
  }
}

const output = document.querySelector('#result')
run().then(
  result => {
    output.dataset.status = 'passed'
    output.textContent = `PASS ${JSON.stringify(result)}`
  },
  error => {
    output.dataset.status = 'failed'
    output.textContent = `FAIL ${error?.stack || error}`
  },
)
