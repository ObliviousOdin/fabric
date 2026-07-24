"""Fabric Link secure device-pairing and remote-authorization primitives.

This package owns protocol and authorization state. It deliberately does not
open a listener or add model tools; relay and UI surfaces consume these narrow
contracts after their own lifecycle gates are satisfied.
"""

from .protocol import FABRIC_LINK_PROTOCOL_VERSION

__all__ = ["FABRIC_LINK_PROTOCOL_VERSION"]
