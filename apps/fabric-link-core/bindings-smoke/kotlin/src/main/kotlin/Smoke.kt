import com.fabric.link.core.fabricLinkControllerApplyCommit
import com.fabric.link.core.fabricLinkControllerDecrypt
import com.fabric.link.core.fabricLinkControllerEncrypt
import com.fabric.link.core.fabricLinkControllerJoin
import com.fabric.link.core.fabricLinkControllerKeyPackage
import com.fabric.link.core.fabricLinkCreateController
import com.fabric.link.core.fabricLinkCreatePair
import com.fabric.link.core.fabricLinkHostEncrypt
import com.fabric.link.core.fabricLinkHostDecrypt
import com.fabric.link.core.fabricLinkHostRemoveController
import com.fabric.link.core.fabricLinkProtocolVersion
import java.io.File
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

fun String.hexBytes(): ByteArray {
    check(length % 2 == 0)
    return chunked(2).map { it.toInt(16).toByte() }.toByteArray()
}

fun corpusString(corpus: String, key: String): String {
    val expression = Regex("\"${Regex.escape(key)}\"\\s*:\\s*\"([^\"]*)\"")
    return expression.find(corpus)?.groupValues?.get(1)
        ?: error("Missing v3 corpus field: $key")
}

fun corpusInt(corpus: String, key: String): Int {
    val expression = Regex("\"${Regex.escape(key)}\"\\s*:\\s*(\\d+)")
    return expression.find(corpus)?.groupValues?.get(1)?.toInt()
        ?: error("Missing v3 corpus integer: $key")
}

fun hkdfSha256(
    input: ByteArray,
    salt: ByteArray,
    info: ByteArray,
    length: Int,
): ByteArray {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(salt, "HmacSHA256"))
    val pseudoRandomKey = mac.doFinal(input)
    val output = ByteArray(length)
    var previous = byteArrayOf()
    var offset = 0
    var counter = 1
    while (offset < length) {
        mac.init(SecretKeySpec(pseudoRandomKey, "HmacSHA256"))
        mac.update(previous)
        mac.update(info)
        mac.update(counter.toByte())
        previous = mac.doFinal()
        val copied = minOf(previous.size, length - offset)
        previous.copyInto(output, offset, 0, copied)
        offset += copied
        counter += 1
    }
    return output
}

fun verifyAesKnownAnswer(
    corpus: String,
    direction: String,
    plaintextKey: String,
) {
    val cipher = Cipher.getInstance("AES/GCM/NoPadding")
    cipher.init(
        Cipher.DECRYPT_MODE,
        SecretKeySpec(
            corpusString(corpus, "enrollment_${direction}_key_hex").hexBytes(),
            "AES",
        ),
        GCMParameterSpec(
            128,
            corpusString(corpus, "enrollment_${direction}_nonce_hex").hexBytes(),
        ),
    )
    cipher.updateAAD(
        corpusString(corpus, "enrollment_${direction}_aad_hex").hexBytes(),
    )
    val plaintext = cipher.doFinal(
        corpusString(
            corpus,
            "enrollment_${direction}_ciphertext_hex",
        ).hexBytes(),
    )
    check(plaintext.contentEquals(corpusString(corpus, plaintextKey).hexBytes()))
}

fun main() {
    val interop = File(
        checkNotNull(System.getenv("FABRIC_LINK_INTEROP_FIXTURE")) {
            "FABRIC_LINK_INTEROP_FIXTURE is required"
        },
    ).readText()
    check(corpusInt(interop, "protocol_version") == fabricLinkProtocolVersion().toInt())
    listOf(
        "pairing_cbor_hex" to "pairing_cbor_sha256_hex",
        "link_request_cbor_hex" to "link_request_sha256_hex",
        "enrollment_request_cbor_hex" to "enrollment_request_sha256_hex",
    ).forEach { (valueKey, digestKey) ->
        val digest = MessageDigest.getInstance("SHA-256").digest(
            corpusString(interop, valueKey).hexBytes(),
        )
        check(digest.contentEquals(corpusString(interop, digestKey).hexBytes()))
    }
    val pairingDigest = MessageDigest.getInstance("SHA-256").digest(
        corpusString(interop, "pairing_cbor_hex").hexBytes(),
    )
    listOf(
        "request" to "fabric-link-enrollment-request-aad-v3",
        "response" to "fabric-link-enrollment-response-aad-v3",
    ).forEach { (direction, domain) ->
        val expectedAad = domain.encodeToByteArray() + byteArrayOf(0) + pairingDigest
        check(
            expectedAad.contentEquals(
                corpusString(
                    interop,
                    "enrollment_${direction}_aad_hex",
                ).hexBytes(),
            ),
        )
    }
    val salt = MessageDigest.getInstance("SHA-256").digest(
        corpusString(interop, "pairing_route_hex").hexBytes() +
            corpusString(interop, "pairing_handle_hex").hexBytes(),
    )
    listOf(
        "fabric-link-enrollment-request-key-v3" to "enrollment_request_key_hex",
        "fabric-link-enrollment-response-key-v3" to "enrollment_response_key_hex",
    ).forEach { (info, expectedKey) ->
        val derived = hkdfSha256(
            corpusString(interop, "pairing_secret_hex").hexBytes(),
            salt,
            info.encodeToByteArray(),
            32,
        )
        check(derived.contentEquals(corpusString(interop, expectedKey).hexBytes()))
    }
    verifyAesKnownAnswer(
        interop,
        "request",
        "enrollment_request_cbor_hex",
    )
    verifyAesKnownAnswer(
        interop,
        "response",
        "enrollment_response_plaintext_cbor_hex",
    )

    val controller = fabricLinkCreateController("kotlin-controller".encodeToByteArray())
    check(
        fabricLinkControllerKeyPackage(controller.opaqueState)
            .contentEquals(controller.keyPackage),
    )
    val pair = fabricLinkCreatePair(
        "kotlin-host".encodeToByteArray(),
        "kotlin-binding-pair".encodeToByteArray(),
        controller.keyPackage,
    )
    val controllerState = fabricLinkControllerJoin(
        controller.opaqueState,
        pair.welcome,
    )
    val encrypted = fabricLinkHostEncrypt(
        pair.hostState,
        "kotlin fixture".encodeToByteArray(),
    )
    val decrypted = fabricLinkControllerDecrypt(
        controllerState,
        encrypted.message,
    )
    check(decrypted.plaintext.contentEquals("kotlin fixture".encodeToByteArray()))

    val controllerEncrypted = fabricLinkControllerEncrypt(
        decrypted.opaqueState,
        "kotlin controller fixture".encodeToByteArray(),
    )
    val hostDecrypted = fabricLinkHostDecrypt(
        encrypted.opaqueState,
        controllerEncrypted.message,
    )
    check(hostDecrypted.plaintext.contentEquals("kotlin controller fixture".encodeToByteArray()))

    val removal = fabricLinkHostRemoveController(hostDecrypted.opaqueState)
    val removed = fabricLinkControllerApplyCommit(
        controllerEncrypted.opaqueState,
        removal.message,
    )
    check(!removed.active)

    System.getenv("FABRIC_LINK_FIXTURE_DIR")?.let { fixturePath ->
        val fixture = File(fixturePath)
        val crossLanguage = fabricLinkControllerDecrypt(
            File(fixture, "controller-state.bin").readBytes(),
            File(fixture, "message.bin").readBytes(),
        )
        check(
            crossLanguage.plaintext.contentEquals(
                File(fixture, "plaintext.bin").readBytes(),
            ),
        )
    }
    println("PASS Kotlin UniFFI bidirectional pairing/restart/removal + v3 corpus")
}
