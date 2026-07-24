//! Shared cryptographic state-machine boundary for Fabric Link.
//!
//! Phase 0 keeps this public surface intentionally small. The MLS group state
//! remains opaque and versioned in Rust while generated native bindings and
//! browser WASM call the same state-machine operations.

use openmls::prelude::Ciphersuite;

mod mls_state;

pub const FABRIC_LINK_PROTOCOL_VERSION: u16 = 3;

#[cfg_attr(not(target_arch = "wasm32"), derive(uniffi::Record))]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FabricLinkBuildInfo {
    pub protocol_version: u16,
    pub ciphersuite: String,
    pub crypto_backend: String,
}

#[cfg_attr(not(target_arch = "wasm32"), derive(uniffi::Record))]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FabricLinkControllerBootstrap {
    pub opaque_state: Vec<u8>,
    pub key_package: Vec<u8>,
}

#[cfg_attr(not(target_arch = "wasm32"), derive(uniffi::Record))]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FabricLinkPairBootstrap {
    pub host_state: Vec<u8>,
    pub welcome: Vec<u8>,
}

#[cfg_attr(not(target_arch = "wasm32"), derive(uniffi::Record))]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FabricLinkStateUpdate {
    pub opaque_state: Vec<u8>,
    pub message: Vec<u8>,
}

#[cfg_attr(not(target_arch = "wasm32"), derive(uniffi::Record))]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FabricLinkDecryption {
    pub opaque_state: Vec<u8>,
    pub plaintext: Vec<u8>,
}

#[cfg_attr(not(target_arch = "wasm32"), derive(uniffi::Record))]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FabricLinkMembershipUpdate {
    pub opaque_state: Vec<u8>,
    pub active: bool,
}

#[cfg_attr(not(target_arch = "wasm32"), derive(uniffi::Error))]
#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum FabricLinkCoreError {
    #[error("invalid argument")]
    InvalidArgument,
    #[error("invalid opaque protocol state")]
    InvalidState,
    #[error("invalid MLS key package")]
    InvalidKeyPackage,
    #[error("invalid MLS welcome")]
    InvalidWelcome,
    #[error("invalid MLS message")]
    InvalidMessage,
    #[error("MLS group is inactive")]
    InactiveGroup,
    #[error("cryptographic operation failed")]
    CryptoFailure,
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
#[cfg_attr(target_arch = "wasm32", wasm_bindgen::prelude::wasm_bindgen)]
pub fn fabric_link_protocol_version() -> u16 {
    FABRIC_LINK_PROTOCOL_VERSION
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
#[cfg_attr(target_arch = "wasm32", wasm_bindgen::prelude::wasm_bindgen)]
pub fn fabric_link_ciphersuite() -> String {
    format!(
        "{:?}",
        Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519
    )
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_build_info() -> FabricLinkBuildInfo {
    FabricLinkBuildInfo {
        protocol_version: FABRIC_LINK_PROTOCOL_VERSION,
        ciphersuite: fabric_link_ciphersuite(),
        crypto_backend: "OpenMLS/RustCrypto".to_string(),
    }
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_create_controller(
    identity: Vec<u8>,
) -> Result<FabricLinkControllerBootstrap, FabricLinkCoreError> {
    mls_state::create_controller(identity)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_controller_key_package(
    opaque_state: Vec<u8>,
) -> Result<Vec<u8>, FabricLinkCoreError> {
    mls_state::controller_key_package(opaque_state)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_create_pair(
    host_identity: Vec<u8>,
    group_id: Vec<u8>,
    controller_key_package: Vec<u8>,
) -> Result<FabricLinkPairBootstrap, FabricLinkCoreError> {
    mls_state::create_pair(host_identity, group_id, controller_key_package)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_controller_join(
    opaque_state: Vec<u8>,
    welcome: Vec<u8>,
) -> Result<Vec<u8>, FabricLinkCoreError> {
    mls_state::controller_join(opaque_state, welcome)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_host_encrypt(
    opaque_state: Vec<u8>,
    plaintext: Vec<u8>,
) -> Result<FabricLinkStateUpdate, FabricLinkCoreError> {
    mls_state::host_encrypt(opaque_state, plaintext)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_controller_encrypt(
    opaque_state: Vec<u8>,
    plaintext: Vec<u8>,
) -> Result<FabricLinkStateUpdate, FabricLinkCoreError> {
    mls_state::controller_encrypt(opaque_state, plaintext)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_host_decrypt(
    opaque_state: Vec<u8>,
    message: Vec<u8>,
) -> Result<FabricLinkDecryption, FabricLinkCoreError> {
    mls_state::host_decrypt(opaque_state, message)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_controller_decrypt(
    opaque_state: Vec<u8>,
    message: Vec<u8>,
) -> Result<FabricLinkDecryption, FabricLinkCoreError> {
    mls_state::controller_decrypt(opaque_state, message)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_host_remove_controller(
    opaque_state: Vec<u8>,
) -> Result<FabricLinkStateUpdate, FabricLinkCoreError> {
    mls_state::host_remove_controller(opaque_state)
}

#[cfg_attr(not(target_arch = "wasm32"), uniffi::export)]
pub fn fabric_link_controller_apply_commit(
    opaque_state: Vec<u8>,
    commit: Vec<u8>,
) -> Result<FabricLinkMembershipUpdate, FabricLinkCoreError> {
    mls_state::controller_apply_commit(opaque_state, commit)
}

#[cfg(target_arch = "wasm32")]
fn wasm_error(error: FabricLinkCoreError) -> wasm_bindgen::JsValue {
    wasm_bindgen::JsValue::from_str(&error.to_string())
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_create_controller(
    identity: Vec<u8>,
) -> Result<Vec<u8>, wasm_bindgen::JsValue> {
    fabric_link_create_controller(identity)
        .map(|bootstrap| bootstrap.opaque_state)
        .map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_controller_key_package(
    opaque_state: Vec<u8>,
) -> Result<Vec<u8>, wasm_bindgen::JsValue> {
    fabric_link_controller_key_package(opaque_state).map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub struct FabricLinkWasmPairBootstrap {
    host_state: Vec<u8>,
    welcome: Vec<u8>,
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
impl FabricLinkWasmPairBootstrap {
    pub fn host_state(&self) -> Vec<u8> {
        self.host_state.clone()
    }

    pub fn welcome(&self) -> Vec<u8> {
        self.welcome.clone()
    }
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub struct FabricLinkWasmStateUpdate {
    opaque_state: Vec<u8>,
    message: Vec<u8>,
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
impl FabricLinkWasmStateUpdate {
    pub fn opaque_state(&self) -> Vec<u8> {
        self.opaque_state.clone()
    }

    pub fn message(&self) -> Vec<u8> {
        self.message.clone()
    }
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub struct FabricLinkWasmDecryption {
    opaque_state: Vec<u8>,
    plaintext: Vec<u8>,
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
impl FabricLinkWasmDecryption {
    pub fn opaque_state(&self) -> Vec<u8> {
        self.opaque_state.clone()
    }

    pub fn plaintext(&self) -> Vec<u8> {
        self.plaintext.clone()
    }
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub struct FabricLinkWasmMembershipUpdate {
    opaque_state: Vec<u8>,
    active: bool,
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
impl FabricLinkWasmMembershipUpdate {
    pub fn opaque_state(&self) -> Vec<u8> {
        self.opaque_state.clone()
    }

    pub fn active(&self) -> bool {
        self.active
    }
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_create_pair(
    host_identity: Vec<u8>,
    group_id: Vec<u8>,
    controller_key_package: Vec<u8>,
) -> Result<FabricLinkWasmPairBootstrap, wasm_bindgen::JsValue> {
    fabric_link_create_pair(host_identity, group_id, controller_key_package)
        .map(|pair| FabricLinkWasmPairBootstrap {
            host_state: pair.host_state,
            welcome: pair.welcome,
        })
        .map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_controller_join(
    opaque_state: Vec<u8>,
    welcome: Vec<u8>,
) -> Result<Vec<u8>, wasm_bindgen::JsValue> {
    fabric_link_controller_join(opaque_state, welcome).map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_host_encrypt(
    opaque_state: Vec<u8>,
    plaintext: Vec<u8>,
) -> Result<FabricLinkWasmStateUpdate, wasm_bindgen::JsValue> {
    fabric_link_host_encrypt(opaque_state, plaintext)
        .map(|update| FabricLinkWasmStateUpdate {
            opaque_state: update.opaque_state,
            message: update.message,
        })
        .map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_controller_encrypt(
    opaque_state: Vec<u8>,
    plaintext: Vec<u8>,
) -> Result<FabricLinkWasmStateUpdate, wasm_bindgen::JsValue> {
    fabric_link_controller_encrypt(opaque_state, plaintext)
        .map(|update| FabricLinkWasmStateUpdate {
            opaque_state: update.opaque_state,
            message: update.message,
        })
        .map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_host_decrypt(
    opaque_state: Vec<u8>,
    message: Vec<u8>,
) -> Result<FabricLinkWasmDecryption, wasm_bindgen::JsValue> {
    fabric_link_host_decrypt(opaque_state, message)
        .map(|decryption| FabricLinkWasmDecryption {
            opaque_state: decryption.opaque_state,
            plaintext: decryption.plaintext,
        })
        .map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_controller_decrypt(
    opaque_state: Vec<u8>,
    message: Vec<u8>,
) -> Result<FabricLinkWasmDecryption, wasm_bindgen::JsValue> {
    fabric_link_controller_decrypt(opaque_state, message)
        .map(|decryption| FabricLinkWasmDecryption {
            opaque_state: decryption.opaque_state,
            plaintext: decryption.plaintext,
        })
        .map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_host_remove_controller(
    opaque_state: Vec<u8>,
) -> Result<FabricLinkWasmStateUpdate, wasm_bindgen::JsValue> {
    fabric_link_host_remove_controller(opaque_state)
        .map(|update| FabricLinkWasmStateUpdate {
            opaque_state: update.opaque_state,
            message: update.message,
        })
        .map_err(wasm_error)
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
pub fn fabric_link_wasm_controller_apply_commit(
    opaque_state: Vec<u8>,
    commit: Vec<u8>,
) -> Result<FabricLinkWasmMembershipUpdate, wasm_bindgen::JsValue> {
    fabric_link_controller_apply_commit(opaque_state, commit)
        .map(|update| FabricLinkWasmMembershipUpdate {
            opaque_state: update.opaque_state,
            active: update.active,
        })
        .map_err(wasm_error)
}

#[cfg(not(target_arch = "wasm32"))]
uniffi::setup_scaffolding!();

#[cfg(test)]
mod tests {
    use super::*;
    use aes_gcm::{
        Aes256Gcm, Nonce,
        aead::{Aead, KeyInit, Payload},
    };
    use hkdf::Hkdf;
    use serde_json::Value;
    use sha2::{Digest, Sha256};

    const INTEROP_CORPUS: &str =
        include_str!("../../../fabric_link/fixtures/v3-interoperability.json");

    fn corpus_string<'a>(corpus: &'a Value, key: &str) -> &'a str {
        corpus[key]
            .as_str()
            .unwrap_or_else(|| panic!("missing corpus string: {key}"))
    }

    fn hex_decode(value: &str) -> Vec<u8> {
        assert_eq!(value.len() % 2, 0, "invalid corpus hex");
        value
            .as_bytes()
            .chunks_exact(2)
            .map(|pair| {
                let encoded = std::str::from_utf8(pair).expect("ASCII corpus hex");
                u8::from_str_radix(encoded, 16).expect("valid corpus hex")
            })
            .collect()
    }

    fn corpus_bytes(corpus: &Value, key: &str) -> Vec<u8> {
        hex_decode(corpus_string(corpus, key))
    }

    fn assert_sha256(corpus: &Value, value_key: &str, digest_key: &str) {
        let digest = Sha256::digest(corpus_bytes(corpus, value_key));
        assert_eq!(
            format!("{digest:x}"),
            corpus_string(corpus, digest_key),
            "{digest_key}"
        );
    }

    #[test]
    fn build_metadata_is_stable_and_non_secret() {
        assert_eq!(
            fabric_link_build_info(),
            FabricLinkBuildInfo {
                protocol_version: 3,
                ciphersuite: "MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519".to_string(),
                crypto_backend: "OpenMLS/RustCrypto".to_string(),
            }
        );
    }

    #[test]
    fn v3_interoperability_known_answers_match_rust_crypto() {
        let corpus: Value = serde_json::from_str(INTEROP_CORPUS).expect("valid corpus JSON");
        assert_eq!(corpus["schema_version"], 1);
        assert_eq!(
            corpus["protocol_version"],
            u64::from(FABRIC_LINK_PROTOCOL_VERSION)
        );
        assert_sha256(&corpus, "pairing_cbor_hex", "pairing_cbor_sha256_hex");
        assert_sha256(&corpus, "link_request_cbor_hex", "link_request_sha256_hex");
        assert_sha256(
            &corpus,
            "enrollment_request_cbor_hex",
            "enrollment_request_sha256_hex",
        );
        let pairing_hash = Sha256::digest(corpus_bytes(&corpus, "pairing_cbor_hex"));
        for (direction, domain) in [
            (
                "request",
                b"fabric-link-enrollment-request-aad-v3\0".as_slice(),
            ),
            (
                "response",
                b"fabric-link-enrollment-response-aad-v3\0".as_slice(),
            ),
        ] {
            assert_eq!(
                [domain, pairing_hash.as_slice()].concat(),
                corpus_bytes(&corpus, &format!("enrollment_{direction}_aad_hex")),
            );
        }

        let route = corpus_bytes(&corpus, "pairing_route_hex");
        let handle = corpus_bytes(&corpus, "pairing_handle_hex");
        let secret = corpus_bytes(&corpus, "pairing_secret_hex");
        let salt = Sha256::digest([route, handle].concat());
        for (info, expected_key) in [
            (
                b"fabric-link-enrollment-request-key-v3".as_slice(),
                "enrollment_request_key_hex",
            ),
            (
                b"fabric-link-enrollment-response-key-v3".as_slice(),
                "enrollment_response_key_hex",
            ),
        ] {
            let mut derived = [0_u8; 32];
            Hkdf::<Sha256>::new(Some(&salt), &secret)
                .expand(info, &mut derived)
                .expect("valid HKDF output length");
            assert_eq!(derived.as_slice(), corpus_bytes(&corpus, expected_key));
        }

        for (direction, plaintext_key) in [
            ("request", "enrollment_request_cbor_hex"),
            ("response", "enrollment_response_plaintext_cbor_hex"),
        ] {
            let key = corpus_bytes(&corpus, &format!("enrollment_{direction}_key_hex"));
            let nonce = corpus_bytes(&corpus, &format!("enrollment_{direction}_nonce_hex"));
            let ciphertext =
                corpus_bytes(&corpus, &format!("enrollment_{direction}_ciphertext_hex"));
            let aad = corpus_bytes(&corpus, &format!("enrollment_{direction}_aad_hex"));
            let plaintext = Aes256Gcm::new_from_slice(&key)
                .expect("AES-256 key")
                .decrypt(
                    Nonce::from_slice(&nonce),
                    Payload {
                        msg: &ciphertext,
                        aad: &aad,
                    },
                )
                .expect("known-answer AES-GCM ciphertext");
            assert_eq!(plaintext, corpus_bytes(&corpus, plaintext_key));
        }
    }
}
