// Mirrors fabric_cli/profiles.py::_PROFILE_ID_RE so we can reject obviously
// invalid names (uppercase, spaces, …) before round-tripping a doomed POST.
// R28: keep this mirror adjacent to every consumer — create + rename share it.
export const PROFILE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
