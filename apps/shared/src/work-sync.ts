import {
  type WorkAttention,
  type WorkCursorReset,
  type WorkEvent,
  type WorkEventSubject,
  type WorkJobSummary,
  type WorkSyncPage,
} from "./work-contract";

export interface WorkSyncScope {
  gateway_id: string;
  profile_id: string;
}

export type WorkProjectionPhase =
  | "empty"
  | "bootstrapping"
  | "syncing"
  | "current";

export interface WorkUnknownProjectionSubject {
  subject_id: string;
  subject_type: string;
  version: number;
  subject: WorkEventSubject;
}

/**
 * Serializable reference projection. The `(gateway, profile, ledger, cursor)`
 * tuple is state authority; live `work.changed` hints never mutate it.
 */
export interface WorkProjection {
  gateway_id: string;
  profile_id: string;
  ledger_id: string | null;
  cursor: number | null;
  watermark: number | null;
  phase: WorkProjectionPhase;
  next_page_token: string | null;
  reset_ledger_hint: string | null;
  jobs: Readonly<Record<string, WorkJobSummary>>;
  attention: Readonly<Record<string, WorkAttention>>;
  unknown_subjects: Readonly<Record<string, WorkUnknownProjectionSubject>>;
  /** Includes tombstone versions, preventing stale subjects from resurrecting. */
  subject_versions: Readonly<Record<string, number>>;
}

export type WorkSyncApplyErrorCode =
  | "identity_changed"
  | "bootstrap_sequence_invalid"
  | "bootstrap_required"
  | "cursor_invalid"
  | "ledger_changed"
  | "page_non_actionable";

export class WorkSyncApplyError extends Error {
  readonly code: WorkSyncApplyErrorCode;

  constructor(code: WorkSyncApplyErrorCode, message: string) {
    super(message);
    this.name = "WorkSyncApplyError";
    this.code = code;
  }
}

export interface WorkSyncRequestContext extends WorkSyncScope {
  /** The token sent to fetch this bootstrap page; null for page one. */
  page_token?: string | null;
  /** The cursor sent to fetch this delta page. */
  after?: number;
}

function nonempty(value: string, field: string): string {
  if (!value.trim()) throw new TypeError(`${field} must be non-empty.`);
  return value;
}

function assertScope(scope: WorkSyncScope): WorkSyncScope {
  return {
    gateway_id: nonempty(scope.gateway_id, "gateway_id"),
    profile_id: nonempty(scope.profile_id, "profile_id"),
  };
}

export function createWorkProjection(scope: WorkSyncScope): WorkProjection {
  const checked = assertScope(scope);
  return {
    ...checked,
    ledger_id: null,
    cursor: null,
    watermark: null,
    phase: "empty",
    next_page_token: null,
    reset_ledger_hint: null,
    jobs: {},
    attention: {},
    unknown_subjects: {},
    subject_versions: {},
  };
}

function sameScope(state: WorkProjection, scope: WorkSyncScope): boolean {
  return (
    state.gateway_id === scope.gateway_id &&
    state.profile_id === scope.profile_id
  );
}

function subjectKey(type: string, id: string): string {
  return `${type}:${id}`;
}

interface MutableProjectionSubjects {
  jobs: Record<string, WorkJobSummary>;
  attention: Record<string, WorkAttention>;
  unknown: Record<string, WorkUnknownProjectionSubject>;
  versions: Record<string, number>;
}

function mutableSubjects(state?: WorkProjection): MutableProjectionSubjects {
  return {
    jobs: state === undefined ? {} : { ...state.jobs },
    attention: state === undefined ? {} : { ...state.attention },
    unknown: state === undefined ? {} : { ...state.unknown_subjects },
    versions: state === undefined ? {} : { ...state.subject_versions },
  };
}

function applyJob(
  mutable: MutableProjectionSubjects,
  job: WorkJobSummary,
): void {
  const key = subjectKey("job", job.job_id);
  if ((mutable.versions[key] ?? 0) >= job.version) return;
  mutable.jobs[job.job_id] = job;
  delete mutable.unknown[key];
  mutable.versions[key] = job.version;
}

function applyAttention(
  mutable: MutableProjectionSubjects,
  attention: WorkAttention,
): void {
  const key = subjectKey("attention", attention.attention_id);
  if ((mutable.versions[key] ?? 0) >= attention.version) return;
  mutable.attention[attention.attention_id] = attention;
  delete mutable.unknown[key];
  mutable.versions[key] = attention.version;
}

function applyEvent(
  mutable: MutableProjectionSubjects,
  event: WorkEvent,
): void {
  const key = subjectKey(event.subject_type, event.subject_id);
  if ((mutable.versions[key] ?? 0) >= event.subject_version) return;

  if (event.tombstone) {
    if (event.subject_type === "job") delete mutable.jobs[event.subject_id];
    if (event.subject_type === "attention") {
      delete mutable.attention[event.subject_id];
    }
    delete mutable.unknown[key];
    mutable.versions[key] = event.subject_version;
    return;
  }

  const subject = event.subject;
  if (subject === null) {
    throw new WorkSyncApplyError(
      "page_non_actionable",
      "A non-tombstone work event has no subject.",
    );
  }
  if (subject.object_type === "job") {
    applyJob(mutable, subject);
    return;
  }
  if (subject.object_type === "attention") {
    applyAttention(mutable, subject);
    return;
  }
  mutable.unknown[key] = {
    subject_id: event.subject_id,
    subject_type: event.subject_type,
    version: event.subject_version,
    subject,
  };
  mutable.versions[key] = event.subject_version;
}

function finishProjection(
  base: Omit<
    WorkProjection,
    "jobs" | "attention" | "unknown_subjects" | "subject_versions"
  >,
  subjects: MutableProjectionSubjects,
): WorkProjection {
  return {
    ...base,
    jobs: subjects.jobs,
    attention: subjects.attention,
    unknown_subjects: subjects.unknown,
    subject_versions: subjects.versions,
  };
}

function applyBootstrap(
  state: WorkProjection,
  page: WorkSyncPage,
  context: WorkSyncRequestContext,
): WorkProjection {
  const requestedToken = context.page_token ?? null;
  const isFirstPage = requestedToken === null;
  let subjects: MutableProjectionSubjects;

  if (isFirstPage) {
    // A fresh bootstrap is always an explicit projection replacement. This is
    // the only page type allowed to change gateway/profile/ledger identity.
    subjects = mutableSubjects();
  } else {
    if (!sameScope(state, context)) {
      throw new WorkSyncApplyError(
        "identity_changed",
        "A bootstrap continuation belongs to a different gateway or profile.",
      );
    }
    if (
      state.phase !== "bootstrapping" ||
      state.next_page_token !== requestedToken
    ) {
      throw new WorkSyncApplyError(
        "bootstrap_sequence_invalid",
        "Bootstrap page token does not match the pending page.",
      );
    }
    if (state.ledger_id !== page.ledger_id) {
      throw new WorkSyncApplyError(
        "ledger_changed",
        "The Work ledger changed during bootstrap; restart at page one.",
      );
    }
    if (state.watermark !== page.watermark) {
      throw new WorkSyncApplyError(
        "cursor_invalid",
        "The fixed bootstrap watermark changed between pages.",
      );
    }
    subjects = mutableSubjects(state);
  }

  // Everything below mutates private copies. No cursor/identity is published
  // until every subject in the page has applied successfully.
  for (const job of page.jobs) applyJob(subjects, job);
  for (const attention of page.attention) applyAttention(subjects, attention);

  return finishProjection(
    {
      gateway_id: context.gateway_id,
      profile_id: context.profile_id,
      ledger_id: page.ledger_id,
      cursor: page.has_more ? null : page.cursor,
      watermark: page.watermark,
      phase: page.has_more ? "bootstrapping" : "current",
      next_page_token: page.next_page_token,
      reset_ledger_hint: null,
    },
    subjects,
  );
}

function applyDelta(
  state: WorkProjection,
  page: WorkSyncPage,
  context: WorkSyncRequestContext,
): WorkProjection {
  if (!sameScope(state, context)) {
    throw new WorkSyncApplyError(
      "identity_changed",
      "The delta belongs to a different gateway or profile; bootstrap first.",
    );
  }
  if (state.phase !== "current" && state.phase !== "syncing") {
    throw new WorkSyncApplyError(
      "bootstrap_required",
      "A delta cannot be applied before bootstrap completes.",
    );
  }
  if (state.ledger_id !== page.ledger_id) {
    throw new WorkSyncApplyError(
      "ledger_changed",
      "The Work ledger changed; discard the projection and bootstrap.",
    );
  }
  if (state.cursor === null) {
    throw new WorkSyncApplyError(
      "bootstrap_required",
      "The projection has no durable cursor.",
    );
  }
  const requestedAfter = context.after ?? state.cursor;
  if (!Number.isSafeInteger(requestedAfter) || requestedAfter < 0) {
    throw new WorkSyncApplyError(
      "cursor_invalid",
      "The requested Work cursor is invalid.",
    );
  }
  if (requestedAfter !== state.cursor) {
    throw new WorkSyncApplyError(
      "cursor_invalid",
      "A stale or future Work response cannot advance this projection.",
    );
  }
  if (page.cursor < state.cursor || page.watermark < state.cursor) {
    throw new WorkSyncApplyError(
      "cursor_invalid",
      "The Work page is behind the persisted cursor.",
    );
  }
  if (page.cursor > state.cursor && page.events.length === 0) {
    throw new WorkSyncApplyError(
      "cursor_invalid",
      "A Work cursor cannot advance without the intervening events.",
    );
  }
  if (page.has_more && page.cursor === state.cursor) {
    throw new WorkSyncApplyError(
      "cursor_invalid",
      "A truncated Work page must advance beyond the persisted cursor.",
    );
  }

  const subjects = mutableSubjects(state);
  let expectedEventId = state.cursor + 1;
  for (const event of page.events) {
    // The persisted monotonic cursor is also the event-id dedupe fence. This
    // makes replaying an already-committed response harmless.
    if (event.event_id <= state.cursor) continue;
    // A valid Work ledger allocates one global event ID per committed event,
    // and retention removes only a contiguous prefix. A gap therefore means
    // this response skipped durable state and must not advance the cursor.
    if (event.event_id !== expectedEventId) {
      throw new WorkSyncApplyError(
        "cursor_invalid",
        "The Work page skipped one or more events after the persisted cursor.",
      );
    }
    applyEvent(subjects, event);
    expectedEventId += 1;
  }
  if (expectedEventId - 1 !== page.cursor) {
    throw new WorkSyncApplyError(
      "cursor_invalid",
      "The Work page cursor does not match its final contiguous event.",
    );
  }

  // Commit the page projection first, then expose its cursor in the returned
  // immutable value. If any event throws, callers retain `state` unchanged.
  return finishProjection(
    {
      gateway_id: state.gateway_id,
      profile_id: state.profile_id,
      ledger_id: state.ledger_id,
      cursor: page.cursor,
      watermark: page.watermark,
      phase: page.has_more ? "syncing" : "current",
      next_page_token: null,
      reset_ledger_hint: null,
    },
    subjects,
  );
}

/**
 * Atomically apply one already-verified page. Unknown object enums remain in
 * the projection for display but their individual `actionable` flag is false.
 */
export function applyWorkSyncPage(
  state: WorkProjection,
  page: WorkSyncPage,
  context: WorkSyncRequestContext,
): WorkProjection {
  assertScope(context);
  if (page.work_profile_id !== context.profile_id) {
    throw new WorkSyncApplyError(
      "identity_changed",
      "The Work page belongs to a different profile.",
    );
  }
  if (!page.actionable) {
    throw new WorkSyncApplyError(
      "page_non_actionable",
      "This client does not understand the Work sync page mode.",
    );
  }
  if (page.mode === "bootstrap") {
    return applyBootstrap(state, page, context);
  }
  if (page.mode === "delta") return applyDelta(state, page, context);
  throw new WorkSyncApplyError(
    "page_non_actionable",
    "This client does not understand the Work sync page mode.",
  );
}

/**
 * Consume a typed cursor reset. The old projection is discarded immediately;
 * only a subsequent page-one bootstrap may establish the replacement ledger.
 */
export function applyWorkCursorReset(
  state: WorkProjection,
  reset: WorkCursorReset,
  scope: WorkSyncScope,
): WorkProjection {
  assertScope(scope);
  if (!sameScope(state, scope)) {
    throw new WorkSyncApplyError(
      "identity_changed",
      "A cursor reset from a different gateway or profile was ignored.",
    );
  }
  return {
    ...createWorkProjection(scope),
    reset_ledger_hint: reset.data.ledger_id,
  };
}
