use fabric_link_core::{
    FabricLinkCoreError, fabric_link_controller_apply_commit, fabric_link_controller_decrypt,
    fabric_link_controller_encrypt, fabric_link_controller_join,
    fabric_link_controller_key_package, fabric_link_create_controller, fabric_link_create_pair,
    fabric_link_host_decrypt, fabric_link_host_encrypt, fabric_link_host_remove_controller,
};

fn paired_states(controller_identity: &[u8], group_id: &[u8]) -> (Vec<u8>, Vec<u8>) {
    let controller =
        fabric_link_create_controller(controller_identity.to_vec()).expect("create controller");
    assert_eq!(
        fabric_link_controller_key_package(controller.opaque_state.clone())
            .expect("recover key package after state restart"),
        controller.key_package
    );
    let pair = fabric_link_create_pair(
        b"fabric-machine".to_vec(),
        group_id.to_vec(),
        controller.key_package,
    )
    .expect("create pair");
    let controller_state =
        fabric_link_controller_join(controller.opaque_state, pair.welcome).expect("join pair");
    (pair.host_state, controller_state)
}

#[test]
fn opaque_binding_state_survives_every_operation_and_controller_removal() {
    let (mut host_state, mut controller_state) =
        paired_states(b"phone-a", b"fabric-binding-restart");

    for plaintext in [b"first record".as_slice(), b"second record".as_slice()] {
        let encrypted = fabric_link_host_encrypt(host_state, plaintext.to_vec())
            .expect("encrypt after restore");
        host_state = encrypted.opaque_state;
        let decrypted = fabric_link_controller_decrypt(controller_state, encrypted.message)
            .expect("decrypt after restore");
        controller_state = decrypted.opaque_state;
        assert_eq!(decrypted.plaintext, plaintext);

        let reply = fabric_link_controller_encrypt(
            controller_state,
            [b"reply: ".as_slice(), plaintext].concat(),
        )
        .expect("controller encrypts after restore");
        controller_state = reply.opaque_state;
        let received = fabric_link_host_decrypt(host_state, reply.message)
            .expect("host decrypts after restore");
        host_state = received.opaque_state;
        assert_eq!(
            received.plaintext,
            [b"reply: ".as_slice(), plaintext].concat()
        );
    }

    let removal =
        fabric_link_host_remove_controller(host_state).expect("remove controller from pair");
    host_state = removal.opaque_state;
    let removed = fabric_link_controller_apply_commit(controller_state, removal.message)
        .expect("controller authenticates its removal");
    assert!(!removed.active);

    let post_removal = fabric_link_host_encrypt(host_state, b"future epoch".to_vec())
        .expect("host advances after controller removal");
    assert_eq!(
        fabric_link_controller_decrypt(removed.opaque_state, post_removal.message),
        Err(FabricLinkCoreError::InactiveGroup)
    );
}

#[test]
fn independent_binding_pair_states_cannot_cross_decrypt() {
    let (host_a, controller_a) = paired_states(b"phone-a", b"binding-pair-a");
    let (_host_b, controller_b) = paired_states(b"desktop-b", b"binding-pair-b");
    let encrypted =
        fabric_link_host_encrypt(host_a, b"controller a only".to_vec()).expect("encrypt");

    assert_eq!(
        fabric_link_controller_decrypt(controller_a, encrypted.message.clone())
            .expect("controller A decrypts")
            .plaintext,
        b"controller a only"
    );
    assert_eq!(
        fabric_link_controller_decrypt(controller_b, encrypted.message),
        Err(FabricLinkCoreError::InvalidMessage)
    );
}

#[test]
fn malformed_binding_inputs_fail_closed() {
    let controller = fabric_link_create_controller(b"phone-a".to_vec()).expect("controller");
    assert_eq!(
        fabric_link_create_pair(
            b"host".to_vec(),
            b"group".to_vec(),
            b"not a key package".to_vec()
        ),
        Err(FabricLinkCoreError::InvalidKeyPackage)
    );
    assert_eq!(
        fabric_link_controller_join(controller.opaque_state.clone(), b"not a welcome".to_vec()),
        Err(FabricLinkCoreError::InvalidWelcome)
    );
    assert_eq!(
        fabric_link_controller_key_package([controller.opaque_state.clone(), vec![0]].concat()),
        Err(FabricLinkCoreError::InvalidState)
    );
    assert_eq!(
        fabric_link_create_controller(Vec::new()),
        Err(FabricLinkCoreError::InvalidArgument)
    );
}
