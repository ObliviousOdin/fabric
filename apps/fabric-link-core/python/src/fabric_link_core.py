"""Build-time placeholder overwritten by the generated UniFFI binding.

Release wheels must never contain this file. ``setup.py`` writes the generated
binding and its adjacent native library into the wheel staging directory.
"""

raise ImportError(
    "fabric-link-core was not built correctly; install a signed release wheel"
)
