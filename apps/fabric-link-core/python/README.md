# Fabric Link Core for Python

`fabric-link-core` is the platform-specific companion to Fabric's universal
Python package. It contains a generated UniFFI binding and the reviewed native
OpenMLS library used by Fabric Link.

Only release-built wheels are supported. There is deliberately no source
distribution, runtime compiler path, or fallback cryptography: if the wheel is
not available for a platform, Fabric Link pairing fails closed.
