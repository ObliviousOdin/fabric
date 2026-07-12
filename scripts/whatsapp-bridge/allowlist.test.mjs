import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';

import {
  expandWhatsAppIdentifiers,
  matchesAllowedUser,
  normalizeWhatsAppIdentifier,
  parseAllowedUsers,
} from './allowlist.js';

test('normalizeWhatsAppIdentifier strips jid syntax and plus prefix', () => {
  assert.equal(normalizeWhatsAppIdentifier('+12025550195@s.whatsapp.net'), '12025550195');
  assert.equal(normalizeWhatsAppIdentifier('900000000000001@lid'), '900000000000001');
  assert.equal(normalizeWhatsAppIdentifier('12025550195:12@s.whatsapp.net'), '12025550195');
});

test('expandWhatsAppIdentifiers resolves phone and lid aliases from session files', () => {
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    writeFileSync(path.join(sessionDir, 'lid-mapping-12025550195.json'), JSON.stringify('900000000000001'));
    writeFileSync(path.join(sessionDir, 'lid-mapping-900000000000001_reverse.json'), JSON.stringify('12025550195'));

    const aliases = expandWhatsAppIdentifiers('900000000000001@lid', sessionDir);
    assert.deepEqual([...aliases].sort(), ['12025550195', '900000000000001']);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});

test('matchesAllowedUser accepts mapped lid sender when allowlist only contains phone number', () => {
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    writeFileSync(path.join(sessionDir, 'lid-mapping-12025550195.json'), JSON.stringify('900000000000001'));
    writeFileSync(path.join(sessionDir, 'lid-mapping-900000000000001_reverse.json'), JSON.stringify('12025550195'));

    const allowedUsers = parseAllowedUsers('+12025550195');
    assert.equal(matchesAllowedUser('900000000000001@lid', allowedUsers, sessionDir), true);
    assert.equal(matchesAllowedUser('900000000000002@lid', allowedUsers, sessionDir), false);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});

test('matchesAllowedUser treats * as allow-all wildcard', () => {
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    const allowedUsers = parseAllowedUsers('*');
    assert.equal(matchesAllowedUser('12025550195@s.whatsapp.net', allowedUsers, sessionDir), true);
    assert.equal(matchesAllowedUser('900000000000001@lid', allowedUsers, sessionDir), true);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});

test('matchesAllowedUser rejects everyone when allowlist is empty (#8389)', () => {
  // Regression guard: empty allowlist used to return true (allow-everyone),
  // which let any stranger DM the bridge and trigger a Python-side
  // pairing-code reply. Secure default is now "reject unless explicitly
  // configured"; operators who want an open bot must set `*`.
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    const empty = parseAllowedUsers('');
    assert.equal(empty.size, 0);
    assert.equal(matchesAllowedUser('12025550195@s.whatsapp.net', empty, sessionDir), false);
    assert.equal(matchesAllowedUser('900000000000001@lid', empty, sessionDir), false);

    // Null/undefined allowlist (defensive) also rejects.
    assert.equal(matchesAllowedUser('12025550195@s.whatsapp.net', null, sessionDir), false);
    assert.equal(matchesAllowedUser('12025550195@s.whatsapp.net', undefined, sessionDir), false);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});
