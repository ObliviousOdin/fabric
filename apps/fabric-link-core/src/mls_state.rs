use std::collections::HashMap;

use openmls::prelude::{
    BasicCredential, Ciphersuite, CredentialWithKey, GroupId, KeyPackage, KeyPackageIn, MlsGroup,
    MlsGroupCreateConfig, MlsGroupJoinConfig, MlsMessageBodyIn, MlsMessageIn,
    ProcessedMessageContent, ProtocolMessage, ProtocolVersion, StagedWelcome,
};
use openmls_basic_credential::SignatureKeyPair;
use openmls_rust_crypto::OpenMlsRustCrypto;
use openmls_traits::{OpenMlsProvider, types::SignatureScheme};
use tls_codec::{Deserialize as _, Serialize as _};

use crate::{
    FabricLinkControllerBootstrap, FabricLinkCoreError, FabricLinkDecryption,
    FabricLinkMembershipUpdate, FabricLinkPairBootstrap, FabricLinkStateUpdate,
};

const STATE_MAGIC: &[u8; 8] = b"FLNKST01";
const STATE_FORMAT_VERSION: u16 = 1;
const MAX_STATE_BYTES: usize = 16 * 1024 * 1024;
const MAX_IDENTITY_BYTES: usize = 256;
const MAX_GROUP_ID_BYTES: usize = 256;
const MAX_FIELD_BYTES: usize = 8 * 1024 * 1024;
const MAX_STORAGE_ENTRIES: usize = 4096;
const CIPHERSUITE: Ciphersuite = Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum StateRole {
    Host = 1,
    Controller = 2,
}

impl StateRole {
    fn from_byte(value: u8) -> Result<Self, FabricLinkCoreError> {
        match value {
            1 => Ok(Self::Host),
            2 => Ok(Self::Controller),
            _ => Err(FabricLinkCoreError::InvalidState),
        }
    }
}

#[derive(Debug)]
struct StateEnvelope {
    role: StateRole,
    identity: Vec<u8>,
    signature_public_key: Vec<u8>,
    key_package: Vec<u8>,
    group_id: Vec<u8>,
    storage: HashMap<Vec<u8>, Vec<u8>>,
}

struct Party {
    provider: OpenMlsRustCrypto,
    credential: CredentialWithKey,
    signer: SignatureKeyPair,
    envelope: StateEnvelope,
}

impl Party {
    fn create(role: StateRole, identity: Vec<u8>) -> Result<Self, FabricLinkCoreError> {
        validate_identity(&identity)?;
        let provider = OpenMlsRustCrypto::default();
        let signer = SignatureKeyPair::new(SignatureScheme::ED25519)
            .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
        signer
            .store(provider.storage())
            .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
        let signature_public_key = signer.public().to_vec();
        let credential = CredentialWithKey {
            credential: BasicCredential::new(identity.clone()).into(),
            signature_key: signature_public_key.clone().into(),
        };
        Ok(Self {
            provider,
            credential,
            signer,
            envelope: StateEnvelope {
                role,
                identity,
                signature_public_key,
                key_package: Vec::new(),
                group_id: Vec::new(),
                storage: HashMap::new(),
            },
        })
    }

    fn restore(state: &[u8], expected_role: StateRole) -> Result<Self, FabricLinkCoreError> {
        let envelope = StateEnvelope::decode(state)?;
        if envelope.role != expected_role {
            return Err(FabricLinkCoreError::InvalidState);
        }
        let provider = OpenMlsRustCrypto::default();
        *provider
            .storage()
            .values
            .write()
            .map_err(|_| FabricLinkCoreError::InvalidState)? = envelope.storage.clone();
        let signer = SignatureKeyPair::read(
            provider.storage(),
            &envelope.signature_public_key,
            SignatureScheme::ED25519,
        )
        .ok_or(FabricLinkCoreError::InvalidState)?;
        let credential = CredentialWithKey {
            credential: BasicCredential::new(envelope.identity.clone()).into(),
            signature_key: envelope.signature_public_key.clone().into(),
        };
        Ok(Self {
            provider,
            credential,
            signer,
            envelope,
        })
    }

    fn export(mut self) -> Result<Vec<u8>, FabricLinkCoreError> {
        self.envelope.storage = self
            .provider
            .storage()
            .values
            .read()
            .map_err(|_| FabricLinkCoreError::InvalidState)?
            .clone();
        self.envelope.encode()
    }

    fn load_group(&self) -> Result<MlsGroup, FabricLinkCoreError> {
        if self.envelope.group_id.is_empty() {
            return Err(FabricLinkCoreError::InvalidState);
        }
        MlsGroup::load(
            self.provider.storage(),
            &GroupId::from_slice(&self.envelope.group_id),
        )
        .map_err(|_| FabricLinkCoreError::InvalidState)?
        .ok_or(FabricLinkCoreError::InvalidState)
    }
}

impl StateEnvelope {
    fn encode(&self) -> Result<Vec<u8>, FabricLinkCoreError> {
        let mut output = Vec::new();
        output.extend_from_slice(STATE_MAGIC);
        output.extend_from_slice(&STATE_FORMAT_VERSION.to_be_bytes());
        output.push(self.role as u8);
        write_field(&mut output, &self.identity)?;
        write_field(&mut output, &self.signature_public_key)?;
        write_field(&mut output, &self.key_package)?;
        write_field(&mut output, &self.group_id)?;

        let mut entries: Vec<_> = self.storage.iter().collect();
        entries.sort_by_key(|(key, _)| *key);
        let count = u32::try_from(entries.len()).map_err(|_| FabricLinkCoreError::InvalidState)?;
        output.extend_from_slice(&count.to_be_bytes());
        for (key, value) in entries {
            write_field(&mut output, key)?;
            write_field(&mut output, value)?;
        }
        if output.len() > MAX_STATE_BYTES {
            return Err(FabricLinkCoreError::InvalidState);
        }
        Ok(output)
    }

    fn decode(input: &[u8]) -> Result<Self, FabricLinkCoreError> {
        if input.len() > MAX_STATE_BYTES {
            return Err(FabricLinkCoreError::InvalidState);
        }
        let mut decoder = Decoder::new(input);
        if decoder.take(STATE_MAGIC.len())? != STATE_MAGIC {
            return Err(FabricLinkCoreError::InvalidState);
        }
        if decoder.read_u16()? != STATE_FORMAT_VERSION {
            return Err(FabricLinkCoreError::InvalidState);
        }
        let role = StateRole::from_byte(decoder.read_u8()?)?;
        let identity = decoder.read_field(MAX_IDENTITY_BYTES)?;
        validate_identity(&identity)?;
        let signature_public_key = decoder.read_field(MAX_FIELD_BYTES)?;
        if signature_public_key.len() != 32 {
            return Err(FabricLinkCoreError::InvalidState);
        }
        let key_package = decoder.read_field(MAX_FIELD_BYTES)?;
        let group_id = decoder.read_field(MAX_GROUP_ID_BYTES)?;
        let count = decoder.read_u32()? as usize;
        if count > MAX_STORAGE_ENTRIES {
            return Err(FabricLinkCoreError::InvalidState);
        }
        let mut storage = HashMap::with_capacity(count);
        for _ in 0..count {
            let key = decoder.read_field(MAX_FIELD_BYTES)?;
            let value = decoder.read_field(MAX_FIELD_BYTES)?;
            if key.is_empty() || storage.insert(key, value).is_some() {
                return Err(FabricLinkCoreError::InvalidState);
            }
        }
        if !decoder.is_finished() {
            return Err(FabricLinkCoreError::InvalidState);
        }
        Ok(Self {
            role,
            identity,
            signature_public_key,
            key_package,
            group_id,
            storage,
        })
    }
}

struct Decoder<'a> {
    input: &'a [u8],
    offset: usize,
}

impl<'a> Decoder<'a> {
    fn new(input: &'a [u8]) -> Self {
        Self { input, offset: 0 }
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], FabricLinkCoreError> {
        let end = self
            .offset
            .checked_add(length)
            .filter(|end| *end <= self.input.len())
            .ok_or(FabricLinkCoreError::InvalidState)?;
        let bytes = &self.input[self.offset..end];
        self.offset = end;
        Ok(bytes)
    }

    fn read_u8(&mut self) -> Result<u8, FabricLinkCoreError> {
        Ok(self.take(1)?[0])
    }

    fn read_u16(&mut self) -> Result<u16, FabricLinkCoreError> {
        let bytes: [u8; 2] = self
            .take(2)?
            .try_into()
            .map_err(|_| FabricLinkCoreError::InvalidState)?;
        Ok(u16::from_be_bytes(bytes))
    }

    fn read_u32(&mut self) -> Result<u32, FabricLinkCoreError> {
        let bytes: [u8; 4] = self
            .take(4)?
            .try_into()
            .map_err(|_| FabricLinkCoreError::InvalidState)?;
        Ok(u32::from_be_bytes(bytes))
    }

    fn read_field(&mut self, maximum: usize) -> Result<Vec<u8>, FabricLinkCoreError> {
        let length = self.read_u32()? as usize;
        if length > maximum {
            return Err(FabricLinkCoreError::InvalidState);
        }
        Ok(self.take(length)?.to_vec())
    }

    fn is_finished(&self) -> bool {
        self.offset == self.input.len()
    }
}

fn write_field(output: &mut Vec<u8>, value: &[u8]) -> Result<(), FabricLinkCoreError> {
    if value.len() > MAX_FIELD_BYTES {
        return Err(FabricLinkCoreError::InvalidState);
    }
    let length = u32::try_from(value.len()).map_err(|_| FabricLinkCoreError::InvalidState)?;
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
    Ok(())
}

fn validate_identity(identity: &[u8]) -> Result<(), FabricLinkCoreError> {
    if identity.is_empty() || identity.len() > MAX_IDENTITY_BYTES {
        return Err(FabricLinkCoreError::InvalidArgument);
    }
    Ok(())
}

fn validate_group_id(group_id: &[u8]) -> Result<(), FabricLinkCoreError> {
    if group_id.is_empty() || group_id.len() > MAX_GROUP_ID_BYTES {
        return Err(FabricLinkCoreError::InvalidArgument);
    }
    Ok(())
}

fn parse_key_package(
    provider: &OpenMlsRustCrypto,
    encoded: &[u8],
) -> Result<KeyPackage, FabricLinkCoreError> {
    if encoded.is_empty() || encoded.len() > MAX_FIELD_BYTES {
        return Err(FabricLinkCoreError::InvalidKeyPackage);
    }
    let incoming = KeyPackageIn::tls_deserialize_exact(encoded)
        .map_err(|_| FabricLinkCoreError::InvalidKeyPackage)?;
    let key_package = incoming
        .validate(provider.crypto(), ProtocolVersion::Mls10)
        .map_err(|_| FabricLinkCoreError::InvalidKeyPackage)?;
    if key_package.ciphersuite() != CIPHERSUITE {
        return Err(FabricLinkCoreError::InvalidKeyPackage);
    }
    Ok(key_package)
}

fn parse_welcome(encoded: &[u8]) -> Result<openmls::prelude::Welcome, FabricLinkCoreError> {
    if encoded.is_empty() || encoded.len() > MAX_FIELD_BYTES {
        return Err(FabricLinkCoreError::InvalidWelcome);
    }
    let message = MlsMessageIn::tls_deserialize_exact(encoded)
        .map_err(|_| FabricLinkCoreError::InvalidWelcome)?;
    match message.extract() {
        MlsMessageBodyIn::Welcome(welcome) => Ok(welcome),
        _ => Err(FabricLinkCoreError::InvalidWelcome),
    }
}

fn parse_protocol_message(encoded: &[u8]) -> Result<ProtocolMessage, FabricLinkCoreError> {
    if encoded.is_empty() || encoded.len() > MAX_FIELD_BYTES {
        return Err(FabricLinkCoreError::InvalidMessage);
    }
    MlsMessageIn::tls_deserialize_exact(encoded)
        .map_err(|_| FabricLinkCoreError::InvalidMessage)?
        .try_into_protocol_message()
        .map_err(|_| FabricLinkCoreError::InvalidMessage)
}

pub(crate) fn create_controller(
    identity: Vec<u8>,
) -> Result<FabricLinkControllerBootstrap, FabricLinkCoreError> {
    let mut controller = Party::create(StateRole::Controller, identity)?;
    let bundle = KeyPackage::builder()
        .build(
            CIPHERSUITE,
            &controller.provider,
            &controller.signer,
            controller.credential.clone(),
        )
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    let key_package = bundle
        .key_package()
        .tls_serialize_detached()
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    controller.envelope.key_package = key_package.clone();
    Ok(FabricLinkControllerBootstrap {
        opaque_state: controller.export()?,
        key_package,
    })
}

pub(crate) fn controller_key_package(
    opaque_state: Vec<u8>,
) -> Result<Vec<u8>, FabricLinkCoreError> {
    let controller = Party::restore(&opaque_state, StateRole::Controller)?;
    if controller.envelope.key_package.is_empty() {
        return Err(FabricLinkCoreError::InvalidState);
    }
    Ok(controller.envelope.key_package)
}

pub(crate) fn create_pair(
    host_identity: Vec<u8>,
    group_id: Vec<u8>,
    controller_key_package: Vec<u8>,
) -> Result<FabricLinkPairBootstrap, FabricLinkCoreError> {
    validate_group_id(&group_id)?;
    let mut host = Party::create(StateRole::Host, host_identity)?;
    let key_package = parse_key_package(&host.provider, &controller_key_package)?;
    let create_config = MlsGroupCreateConfig::builder()
        .ciphersuite(CIPHERSUITE)
        .use_ratchet_tree_extension(true)
        .build();
    let mut group = MlsGroup::new_with_group_id(
        &host.provider,
        &host.signer,
        &create_config,
        GroupId::from_slice(&group_id),
        host.credential.clone(),
    )
    .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    let (_, welcome, _) = group
        .add_members(&host.provider, &host.signer, &[key_package])
        .map_err(|_| FabricLinkCoreError::InvalidKeyPackage)?;
    group
        .merge_pending_commit(&host.provider)
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    host.envelope.group_id = group_id;
    let welcome = welcome
        .tls_serialize_detached()
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    Ok(FabricLinkPairBootstrap {
        host_state: host.export()?,
        welcome,
    })
}

pub(crate) fn controller_join(
    opaque_state: Vec<u8>,
    welcome: Vec<u8>,
) -> Result<Vec<u8>, FabricLinkCoreError> {
    let mut controller = Party::restore(&opaque_state, StateRole::Controller)?;
    if !controller.envelope.group_id.is_empty() {
        return Err(FabricLinkCoreError::InvalidState);
    }
    let welcome = parse_welcome(&welcome)?;
    let join_config = MlsGroupJoinConfig::builder()
        .use_ratchet_tree_extension(true)
        .build();
    let group = StagedWelcome::new_from_welcome(&controller.provider, &join_config, welcome, None)
        .map_err(|_| FabricLinkCoreError::InvalidWelcome)?
        .into_group(&controller.provider)
        .map_err(|_| FabricLinkCoreError::InvalidWelcome)?;
    if group.group_id().as_slice().is_empty()
        || group.group_id().as_slice().len() > MAX_GROUP_ID_BYTES
    {
        return Err(FabricLinkCoreError::InvalidWelcome);
    }
    controller.envelope.group_id = group.group_id().as_slice().to_vec();
    controller.envelope.key_package.clear();
    controller.export()
}

pub(crate) fn host_encrypt(
    opaque_state: Vec<u8>,
    plaintext: Vec<u8>,
) -> Result<FabricLinkStateUpdate, FabricLinkCoreError> {
    if plaintext.is_empty() || plaintext.len() > MAX_FIELD_BYTES {
        return Err(FabricLinkCoreError::InvalidArgument);
    }
    let host = Party::restore(&opaque_state, StateRole::Host)?;
    let mut group = host.load_group()?;
    if !group.is_active() {
        return Err(FabricLinkCoreError::InactiveGroup);
    }
    let message = group
        .create_message(&host.provider, &host.signer, &plaintext)
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?
        .tls_serialize_detached()
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    Ok(FabricLinkStateUpdate {
        opaque_state: host.export()?,
        message,
    })
}

pub(crate) fn controller_encrypt(
    opaque_state: Vec<u8>,
    plaintext: Vec<u8>,
) -> Result<FabricLinkStateUpdate, FabricLinkCoreError> {
    if plaintext.is_empty() || plaintext.len() > MAX_FIELD_BYTES {
        return Err(FabricLinkCoreError::InvalidArgument);
    }
    let controller = Party::restore(&opaque_state, StateRole::Controller)?;
    let mut group = controller.load_group()?;
    if !group.is_active() {
        return Err(FabricLinkCoreError::InactiveGroup);
    }
    let message = group
        .create_message(&controller.provider, &controller.signer, &plaintext)
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?
        .tls_serialize_detached()
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    Ok(FabricLinkStateUpdate {
        opaque_state: controller.export()?,
        message,
    })
}

pub(crate) fn host_decrypt(
    opaque_state: Vec<u8>,
    message: Vec<u8>,
) -> Result<FabricLinkDecryption, FabricLinkCoreError> {
    let host = Party::restore(&opaque_state, StateRole::Host)?;
    let mut group = host.load_group()?;
    if !group.is_active() {
        return Err(FabricLinkCoreError::InactiveGroup);
    }
    let processed = group
        .process_message(&host.provider, parse_protocol_message(&message)?)
        .map_err(|_| FabricLinkCoreError::InvalidMessage)?;
    let plaintext = match processed.into_content() {
        ProcessedMessageContent::ApplicationMessage(application) => application.into_bytes(),
        _ => return Err(FabricLinkCoreError::InvalidMessage),
    };
    Ok(FabricLinkDecryption {
        opaque_state: host.export()?,
        plaintext,
    })
}

pub(crate) fn controller_decrypt(
    opaque_state: Vec<u8>,
    message: Vec<u8>,
) -> Result<FabricLinkDecryption, FabricLinkCoreError> {
    let controller = Party::restore(&opaque_state, StateRole::Controller)?;
    let mut group = controller.load_group()?;
    if !group.is_active() {
        return Err(FabricLinkCoreError::InactiveGroup);
    }
    let processed = group
        .process_message(&controller.provider, parse_protocol_message(&message)?)
        .map_err(|_| FabricLinkCoreError::InvalidMessage)?;
    let plaintext = match processed.into_content() {
        ProcessedMessageContent::ApplicationMessage(application) => application.into_bytes(),
        _ => return Err(FabricLinkCoreError::InvalidMessage),
    };
    Ok(FabricLinkDecryption {
        opaque_state: controller.export()?,
        plaintext,
    })
}

pub(crate) fn host_remove_controller(
    opaque_state: Vec<u8>,
) -> Result<FabricLinkStateUpdate, FabricLinkCoreError> {
    let host = Party::restore(&opaque_state, StateRole::Host)?;
    let mut group = host.load_group()?;
    let own_index = group.own_leaf_index();
    let controller_index = group
        .members()
        .find(|member| member.index != own_index)
        .ok_or(FabricLinkCoreError::InvalidState)?
        .index;
    let (commit, _, _) = group
        .remove_members(&host.provider, &host.signer, &[controller_index])
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    group
        .merge_pending_commit(&host.provider)
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    let message = commit
        .tls_serialize_detached()
        .map_err(|_| FabricLinkCoreError::CryptoFailure)?;
    Ok(FabricLinkStateUpdate {
        opaque_state: host.export()?,
        message,
    })
}

pub(crate) fn controller_apply_commit(
    opaque_state: Vec<u8>,
    commit: Vec<u8>,
) -> Result<FabricLinkMembershipUpdate, FabricLinkCoreError> {
    let controller = Party::restore(&opaque_state, StateRole::Controller)?;
    let mut group = controller.load_group()?;
    let processed = group
        .process_message(&controller.provider, parse_protocol_message(&commit)?)
        .map_err(|_| FabricLinkCoreError::InvalidMessage)?;
    let staged = match processed.into_content() {
        ProcessedMessageContent::StagedCommitMessage(staged) => staged,
        _ => return Err(FabricLinkCoreError::InvalidMessage),
    };
    group
        .merge_staged_commit(&controller.provider, *staged)
        .map_err(|_| FabricLinkCoreError::InvalidMessage)?;
    let active = group.is_active();
    Ok(FabricLinkMembershipUpdate {
        opaque_state: controller.export()?,
        active,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn state_envelope_encoding_has_a_stable_known_prefix_and_round_trips() {
        let envelope = StateEnvelope {
            role: StateRole::Controller,
            identity: b"phone".to_vec(),
            signature_public_key: vec![7; 32],
            key_package: b"package".to_vec(),
            group_id: Vec::new(),
            storage: HashMap::from([(b"k".to_vec(), b"v".to_vec())]),
        };
        let encoded = envelope.encode().expect("encode state");
        assert_eq!(
            &encoded[..15],
            b"FLNKST01\x00\x01\x02\x00\x00\x00\x05",
            "state version, role, and first bounded field are a known answer"
        );
        let decoded = StateEnvelope::decode(&encoded).expect("decode state");
        assert_eq!(decoded.identity, b"phone");
        assert_eq!(decoded.storage.get(b"k".as_slice()), Some(&b"v".to_vec()));
    }

    #[test]
    fn malformed_state_is_rejected_without_partial_acceptance() {
        let bootstrap = create_controller(b"phone".to_vec()).expect("controller");
        for malformed in [
            Vec::new(),
            bootstrap.opaque_state[..12].to_vec(),
            [bootstrap.opaque_state.clone(), vec![0]].concat(),
        ] {
            assert_eq!(
                controller_key_package(malformed),
                Err(FabricLinkCoreError::InvalidState)
            );
        }
    }
}
