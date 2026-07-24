package io.github.obliviousodin.fabric.mobile.core

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Opaque Fabric Link MLS state guarded by an Android Keystore key.
 *
 * Link state contains controller private key material, so it is never placed
 * in SharedPreferences or in an auto-reconnect path. The encrypted payload is
 * an app-private, no-backup file and the non-exportable key requires explicit
 * authentication for every cipher use. Android 11+ accepts a strong biometric
 * or device credential; Android 8–10 uses per-operation biometric auth.
 *
 * Foreground Link UI must pass [EncryptOperation.cipher] or
 * [DecryptOperation.cipher] to `BiometricPrompt.CryptoObject`; after a
 * successful prompt it passes the returned cipher to `completeWrite` or
 * `completeRead`. This API intentionally has no unauthenticated `read`.
 */
internal object LinkControllerStore {
    private const val ANDROID_KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "fabric.mobile.link.controller.state.v1"
    private const val DIRECTORY = "fabric-link-controller-state-v1"
    private const val FILE_SUFFIX = ".state"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val PAYLOAD_VERSION = "v1"
    private const val MAX_STATE_BYTES = 16 * 1024 * 1024

    internal class EncryptOperation internal constructor(
        internal val controllerId: String,
        internal val cipher: Cipher,
    )

    internal class DecryptOperation internal constructor(
        internal val controllerId: String,
        private val ciphertext: ByteArray,
        internal val cipher: Cipher,
    ) {
        internal fun decrypt(authenticatedCipher: Cipher): ByteArray {
            require(authenticatedCipher === cipher) {
                "Fabric Link cipher does not belong to this authentication operation"
            }
            return authenticatedCipher.doFinal(ciphertext)
        }
    }

    fun beginWrite(controllerId: String): EncryptOperation {
        validateControllerId(controllerId)
        val cipher = Cipher.getInstance(TRANSFORMATION).apply {
            init(Cipher.ENCRYPT_MODE, key())
            updateAAD(aad(controllerId))
        }
        return EncryptOperation(controllerId, cipher)
    }

    fun completeWrite(
        context: Context,
        operation: EncryptOperation,
        authenticatedCipher: Cipher,
        opaqueState: ByteArray,
    ) {
        require(opaqueState.isNotEmpty() && opaqueState.size <= MAX_STATE_BYTES) {
            "Fabric Link controller state is invalid"
        }
        require(authenticatedCipher === operation.cipher) {
            "Fabric Link cipher does not belong to this authentication operation"
        }
        val ciphertext = authenticatedCipher.doFinal(opaqueState)
        val payload = listOf(
            PAYLOAD_VERSION,
            Base64.encodeToString(authenticatedCipher.iv, Base64.NO_WRAP),
            Base64.encodeToString(ciphertext, Base64.NO_WRAP),
        ).joinToString(":")
        atomicFile(context, operation.controllerId).writeText(payload)
    }

    fun beginRead(context: Context, controllerId: String): DecryptOperation? {
        validateControllerId(controllerId)
        val target = file(context, controllerId)
        if (!target.exists()) return null
        val (iv, ciphertext) = parsePayload(target.readText())
        val cipher = Cipher.getInstance(TRANSFORMATION).apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            updateAAD(aad(controllerId))
        }
        return DecryptOperation(controllerId, ciphertext, cipher)
    }

    fun completeRead(
        operation: DecryptOperation,
        authenticatedCipher: Cipher,
    ): ByteArray {
        val opaqueState = operation.decrypt(authenticatedCipher)
        require(opaqueState.isNotEmpty() && opaqueState.size <= MAX_STATE_BYTES) {
            "Fabric Link controller state is invalid"
        }
        return opaqueState
    }

    fun remove(context: Context, controllerId: String) {
        validateControllerId(controllerId)
        val target = file(context, controllerId)
        if (target.exists()) {
            check(target.delete()) { "Unable to remove protected Fabric Link state" }
        }
    }

    private fun atomicFile(context: Context, controllerId: String): AtomicFile = AtomicFile(file(context, controllerId))

    private fun AtomicFile.writeText(payload: String) {
        val output = startWrite()
        try {
            output.write(payload.toByteArray(Charsets.US_ASCII))
            finishWrite(output)
        } catch (error: Throwable) {
            failWrite(output)
            throw error
        }
    }

    private fun file(context: Context, controllerId: String): File {
        val directory = File(context.noBackupFilesDir, DIRECTORY)
        check(directory.exists() || directory.mkdirs()) {
            "Unable to prepare protected Fabric Link state storage"
        }
        return File(directory, controllerId + FILE_SUFFIX)
    }

    private fun parsePayload(payload: String): Pair<ByteArray, ByteArray> {
        val parts = payload.split(':', limit = 3)
        require(parts.size == 3 && parts[0] == PAYLOAD_VERSION) {
            "Unsupported protected Fabric Link state payload"
        }
        val iv = Base64.decode(parts[1], Base64.NO_WRAP)
        val ciphertext = Base64.decode(parts[2], Base64.NO_WRAP)
        require(iv.size == 12 && ciphertext.isNotEmpty()) {
            "Invalid protected Fabric Link state payload"
        }
        return iv to ciphertext
    }

    private fun aad(controllerId: String): ByteArray =
        "fabric-link-controller-state-v1:$controllerId".toByteArray(Charsets.UTF_8)

    private fun validateControllerId(controllerId: String) {
        require(
            controllerId.isNotEmpty()
                && controllerId.length <= 128
                && controllerId.all { it.isLetterOrDigit() || it == '.' || it == '_' || it == '-' },
        ) { "Invalid Fabric Link controller identifier" }
    }

    @Synchronized
    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }

        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
            .apply {
                init(
                    KeyGenParameterSpec.Builder(
                        KEY_ALIAS,
                        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                    )
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setKeySize(256)
                        .setRandomizedEncryptionRequired(true)
                        .setUserAuthenticationRequired(true)
                        .apply {
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                                setUserAuthenticationParameters(
                                    0,
                                    KeyProperties.AUTH_BIOMETRIC_STRONG
                                        or KeyProperties.AUTH_DEVICE_CREDENTIAL,
                                )
                            } else {
                                @Suppress("DEPRECATION")
                                setUserAuthenticationValidityDurationSeconds(-1)
                            }
                        }
                        .build()
                )
            }
            .generateKey()
    }
}
