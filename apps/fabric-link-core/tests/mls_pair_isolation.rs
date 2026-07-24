use openmls::prelude::{
    BasicCredential, Ciphersuite, CredentialWithKey, GroupId, KeyPackage, MlsGroup,
    MlsGroupCreateConfig, MlsGroupJoinConfig, MlsMessageBodyIn, MlsMessageIn,
    ProcessedMessageContent, ProtocolMessage, StagedWelcome, tls_codec::*,
};
use openmls_basic_credential::SignatureKeyPair;
use openmls_rust_crypto::OpenMlsRustCrypto;
use openmls_traits::{OpenMlsProvider, types::SignatureScheme};

const CIPHERSUITE: Ciphersuite = Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519;

struct Party {
    provider: OpenMlsRustCrypto,
    credential: CredentialWithKey,
    signer: SignatureKeyPair,
}

impl Party {
    fn new(identity: &[u8]) -> Self {
        let provider = OpenMlsRustCrypto::default();
        let signer = SignatureKeyPair::new(SignatureScheme::ED25519).expect("create signer");
        signer
            .store(provider.storage())
            .expect("store signer in party provider");
        let credential = CredentialWithKey {
            credential: BasicCredential::new(identity.to_vec()).into(),
            signature_key: signer.to_public_vec().into(),
        };
        Self {
            provider,
            credential,
            signer,
        }
    }

    fn key_package(&self) -> KeyPackage {
        KeyPackage::builder()
            .build(
                CIPHERSUITE,
                &self.provider,
                &self.signer,
                self.credential.clone(),
            )
            .expect("build key package")
            .key_package()
            .clone()
    }
}

fn create_pair_group(host: &Party, controller: &Party, group_id: &[u8]) -> (MlsGroup, MlsGroup) {
    let create_config = MlsGroupCreateConfig::builder()
        .ciphersuite(CIPHERSUITE)
        .use_ratchet_tree_extension(true)
        .build();
    let mut host_group = MlsGroup::new_with_group_id(
        &host.provider,
        &host.signer,
        &create_config,
        GroupId::from_slice(group_id),
        host.credential.clone(),
    )
    .expect("create host pair group");
    let (_, welcome, _) = host_group
        .add_members(&host.provider, &host.signer, &[controller.key_package()])
        .expect("add controller");
    host_group
        .merge_pending_commit(&host.provider)
        .expect("merge host add");

    let welcome_message =
        MlsMessageIn::tls_deserialize_exact(welcome.to_bytes().expect("serialize welcome"))
            .expect("deserialize welcome");
    let welcome = match welcome_message.extract() {
        MlsMessageBodyIn::Welcome(welcome) => welcome,
        other => panic!("expected welcome, got {other:?}"),
    };
    let join_config = MlsGroupJoinConfig::builder()
        .use_ratchet_tree_extension(true)
        .build();
    let controller_group =
        StagedWelcome::new_from_welcome(&controller.provider, &join_config, welcome, None)
            .expect("stage controller welcome")
            .into_group(&controller.provider)
            .expect("join controller to pair group");
    (host_group, controller_group)
}

fn encrypted_message(host: &Party, group: &mut MlsGroup, plaintext: &[u8]) -> Vec<u8> {
    group
        .create_message(&host.provider, &host.signer, plaintext)
        .expect("encrypt application message")
        .to_bytes()
        .expect("serialize application message")
}

fn decrypt_message(
    controller: &Party,
    group: &mut MlsGroup,
    ciphertext: Vec<u8>,
) -> Result<Vec<u8>, String> {
    let message = MlsMessageIn::tls_deserialize_exact(ciphertext)
        .map_err(|error| format!("decode: {error:?}"))?;
    let protocol: ProtocolMessage = message
        .try_into_protocol_message()
        .map_err(|error| format!("protocol: {error:?}"))?;
    let processed = group
        .process_message(&controller.provider, protocol)
        .map_err(|error| format!("decrypt: {error:?}"))?;
    match processed.into_content() {
        ProcessedMessageContent::ApplicationMessage(application) => Ok(application.into_bytes()),
        other => Err(format!("unexpected message content: {other:?}")),
    }
}

#[test]
fn independent_controller_pair_groups_cannot_cross_decrypt() {
    let host = Party::new(b"fabric-machine");
    let controller_a = Party::new(b"phone-a");
    let controller_b = Party::new(b"desktop-b");
    let (mut host_a, mut group_a) = create_pair_group(&host, &controller_a, b"fabric-pair-a");
    let (_host_b, mut group_b) = create_pair_group(&host, &controller_b, b"fabric-pair-b");

    let ciphertext = encrypted_message(&host, &mut host_a, b"only controller a");
    assert_eq!(
        decrypt_message(&controller_a, &mut group_a, ciphertext.clone())
            .expect("controller A decrypts its pair group"),
        b"only controller a"
    );
    assert!(
        decrypt_message(&controller_b, &mut group_b, ciphertext).is_err(),
        "controller B must not decrypt controller A's pair-group record"
    );
}

#[test]
fn removed_controller_cannot_decrypt_the_next_epoch() {
    let host = Party::new(b"fabric-machine");
    let controller = Party::new(b"lost-phone");
    let (mut host_group, mut controller_group) =
        create_pair_group(&host, &controller, b"fabric-removal");

    let controller_index = host_group
        .members()
        .find(|member| {
            member.credential.serialized_content()
                == controller.credential.credential.serialized_content()
        })
        .expect("controller membership")
        .index;
    let (remove_commit, _, _) = host_group
        .remove_members(&host.provider, &host.signer, &[controller_index])
        .expect("remove controller");
    host_group
        .merge_pending_commit(&host.provider)
        .expect("merge host removal");

    let remove_protocol =
        MlsMessageIn::tls_deserialize_exact(remove_commit.to_bytes().expect("serialize removal"))
            .expect("deserialize removal")
            .try_into_protocol_message()
            .expect("removal protocol message");
    let processed = controller_group
        .process_message(&controller.provider, remove_protocol)
        .expect("removed controller authenticates removal commit");
    let staged = match processed.into_content() {
        ProcessedMessageContent::StagedCommitMessage(staged) => staged,
        other => panic!("expected staged removal commit, got {other:?}"),
    };
    controller_group
        .merge_staged_commit(&controller.provider, *staged)
        .expect("merge controller removal");
    assert!(!controller_group.is_active());

    let post_removal = encrypted_message(&host, &mut host_group, b"future epoch");
    assert!(
        decrypt_message(&controller, &mut controller_group, post_removal).is_err(),
        "removed controller must not decrypt post-removal application data"
    );
}
