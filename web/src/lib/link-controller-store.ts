/**
 * Browser-only protection for one paired Fabric Link controller's opaque MLS
 * state. The state is never sent to localStorage, cookies, or the Fabric
 * dashboard API: IndexedDB holds a non-extractable WebCrypto wrapping key and
 * an AES-GCM ciphertext envelope instead.
 */

const DATABASE_NAME = "fabric-link-controller-v1";
const DATABASE_VERSION = 1;
const STORE_NAME = "link-controller-state";
const WRAPPING_KEY_RECORD = "wrapping-key-v1";
const STATE_RECORD_PREFIX = "state-v1:";
const ENVELOPE_VERSION = 1;
const MAX_STATE_BYTES = 16 * 1024 * 1024;
const CONTROLLER_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

interface StoredStateEnvelope {
  version: number;
  controllerId: string;
  iv: ArrayBuffer;
  ciphertext: ArrayBuffer;
}

interface PersistedRecords {
  key: unknown;
  state: unknown;
}

export class LinkControllerWebStoreUnavailable extends Error {
  constructor(message = "Secure browser storage is unavailable for Fabric Link") {
    super(message);
    this.name = "LinkControllerWebStoreUnavailable";
  }
}

export class LinkControllerWebStoreCorrupt extends Error {
  constructor(message = "Protected Fabric Link state is invalid") {
    super(message);
    this.name = "LinkControllerWebStoreCorrupt";
  }
}

/**
 * A controller-local, browser-scoped store. It intentionally exposes only
 * opaque MLS bytes. Pair metadata, grants, and relay credentials belong to the
 * authenticated protocol layer, not browser persistence.
 */
export class LinkControllerWebStore {
  async load(controllerId: string): Promise<Uint8Array | undefined> {
    validateControllerId(controllerId);
    const database = await openDatabase();
    try {
      const records = await readRecords(database, controllerId);
      if (records.state === undefined && records.key === undefined) return undefined;
      if (!isCryptoKey(records.key) || !isStoredStateEnvelope(records.state)) {
        throw new LinkControllerWebStoreCorrupt();
      }
      validateKey(records.key);
      validateEnvelope(records.state, controllerId);
      try {
        const plaintext = await crypto.subtle.decrypt(
          {
            name: "AES-GCM",
            iv: records.state.iv,
            additionalData: stateAad(controllerId),
          },
          records.key,
          records.state.ciphertext,
        );
        return validateOpaqueState(new Uint8Array(plaintext));
      } catch (error) {
        if (error instanceof LinkControllerWebStoreCorrupt) throw error;
        throw new LinkControllerWebStoreCorrupt();
      }
    } finally {
      database.close();
    }
  }

  async store(controllerId: string, opaqueState: Uint8Array): Promise<void> {
    validateControllerId(controllerId);
    const state = validateOpaqueState(opaqueState);
    const database = await openDatabase();
    try {
      const existingKey = await readWrappingKey(database);
      const wrappingKey = existingKey ?? (await createWrappingKey());
      validateKey(wrappingKey);
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = await crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv: copyArrayBuffer(iv),
          additionalData: stateAad(controllerId),
        },
        wrappingKey,
        copyArrayBuffer(state),
      );
      await writeRecords(database, controllerId, wrappingKey, {
        version: ENVELOPE_VERSION,
        controllerId,
        iv: copyArrayBuffer(iv),
        ciphertext,
      });
    } catch (error) {
      if (error instanceof LinkControllerWebStoreCorrupt) throw error;
      throw new LinkControllerWebStoreUnavailable();
    } finally {
      database.close();
    }
  }

  async remove(controllerId: string): Promise<void> {
    validateControllerId(controllerId);
    const database = await openDatabase();
    try {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).delete(stateRecordId(controllerId));
      await transactionComplete(transaction);
    } catch {
      throw new LinkControllerWebStoreUnavailable();
    } finally {
      database.close();
    }
  }
}

function validateControllerId(controllerId: string): void {
  if (!CONTROLLER_ID_PATTERN.test(controllerId)) {
    throw new LinkControllerWebStoreCorrupt("Fabric Link controller identifier is invalid");
  }
}

function validateOpaqueState(opaqueState: Uint8Array): Uint8Array {
  if (!(opaqueState instanceof Uint8Array) || opaqueState.byteLength === 0 || opaqueState.byteLength > MAX_STATE_BYTES) {
    throw new LinkControllerWebStoreCorrupt();
  }
  return opaqueState;
}

function validateKey(key: CryptoKey): void {
  if (key.extractable || key.type !== "secret") {
    throw new LinkControllerWebStoreCorrupt();
  }
  if (!key.usages.includes("encrypt") || !key.usages.includes("decrypt")) {
    throw new LinkControllerWebStoreCorrupt();
  }
}

function validateEnvelope(envelope: StoredStateEnvelope, controllerId: string): void {
  if (
    !envelope
    || envelope.version !== ENVELOPE_VERSION
    || envelope.controllerId !== controllerId
    || !(envelope.iv instanceof ArrayBuffer)
    || envelope.iv.byteLength !== 12
    || !(envelope.ciphertext instanceof ArrayBuffer)
    || envelope.ciphertext.byteLength === 0
  ) {
    throw new LinkControllerWebStoreCorrupt();
  }
}

function stateAad(controllerId: string): ArrayBuffer {
  return copyArrayBuffer(
    new TextEncoder().encode(`fabric-link-web-controller-state-v1\0${controllerId}`),
  );
}

function stateRecordId(controllerId: string): string {
  return `${STATE_RECORD_PREFIX}${controllerId}`;
}

function copyArrayBuffer(value: Uint8Array): ArrayBuffer {
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer;
}

async function createWrappingKey(): Promise<CryptoKey> {
  const key = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  if (!isCryptoKey(key)) {
    throw new LinkControllerWebStoreUnavailable();
  }
  return key;
}

async function openDatabase(): Promise<IDBDatabase> {
  if (!globalThis.isSecureContext || !globalThis.crypto?.subtle || !globalThis.indexedDB) {
    throw new LinkControllerWebStoreUnavailable(
      "Fabric Link browser control requires HTTPS, WebCrypto, and IndexedDB",
    );
  }
  const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
  request.addEventListener("upgradeneeded", () => {
    if (!request.result.objectStoreNames.contains(STORE_NAME)) {
      request.result.createObjectStore(STORE_NAME);
    }
  });
  try {
    return await requestResult(request);
  } catch {
    throw new LinkControllerWebStoreUnavailable();
  }
}

async function readRecords(database: IDBDatabase, controllerId: string): Promise<PersistedRecords> {
  const transaction = database.transaction(STORE_NAME, "readonly");
  const store = transaction.objectStore(STORE_NAME);
  try {
    const [key, state] = await Promise.all([
      requestResult(store.get(WRAPPING_KEY_RECORD)),
      requestResult(store.get(stateRecordId(controllerId))),
    ]);
    await transactionComplete(transaction);
    return {
      key,
      state,
    };
  } catch {
    throw new LinkControllerWebStoreUnavailable();
  }
}

async function readWrappingKey(database: IDBDatabase): Promise<CryptoKey | undefined> {
  const transaction = database.transaction(STORE_NAME, "readonly");
  try {
    const key = await requestResult(transaction.objectStore(STORE_NAME).get(WRAPPING_KEY_RECORD));
    await transactionComplete(transaction);
    if (key === undefined) return undefined;
    if (!isCryptoKey(key)) throw new LinkControllerWebStoreCorrupt();
    return key;
  } catch (error) {
    if (error instanceof LinkControllerWebStoreCorrupt) throw error;
    throw new LinkControllerWebStoreUnavailable();
  }
}

async function writeRecords(
  database: IDBDatabase,
  controllerId: string,
  key: CryptoKey,
  state: StoredStateEnvelope,
): Promise<void> {
  const transaction = database.transaction(STORE_NAME, "readwrite");
  const store = transaction.objectStore(STORE_NAME);
  store.put(key, WRAPPING_KEY_RECORD);
  store.put(state, stateRecordId(controllerId));
  try {
    await transactionComplete(transaction);
  } catch {
    throw new LinkControllerWebStoreUnavailable();
  }
}

function isStoredStateEnvelope(value: unknown): value is StoredStateEnvelope {
  return typeof value === "object" && value !== null;
}

function isCryptoKey(value: unknown): value is CryptoKey {
  return typeof CryptoKey !== "undefined" && value instanceof CryptoKey;
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.addEventListener("success", () => resolve(request.result), { once: true });
    request.addEventListener("error", () => reject(request.error), { once: true });
  });
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.addEventListener("complete", () => resolve(), { once: true });
    transaction.addEventListener("abort", () => reject(transaction.error), { once: true });
    transaction.addEventListener("error", () => reject(transaction.error), { once: true });
  });
}
