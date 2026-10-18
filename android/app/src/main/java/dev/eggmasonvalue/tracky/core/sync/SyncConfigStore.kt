package dev.eggmasonvalue.tracky.core.sync

import android.content.Context
import android.util.Base64
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties

/**
 * Stores the endpoint as configuration and the bearer token as AES-GCM ciphertext backed by the
 * Android Keystore. There is no endpoint or token default in the application.
 */
class SecureSyncConfigStore(context: Context) : SyncConfigSource {
    private val appContext = context.applicationContext
    private val preferences = appContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    override fun load(): SyncEndpointConfig? {
        val endpoint = preferences.getString(KEY_ENDPOINT, null) ?: return null
        val encryptedToken = preferences.getString(KEY_TOKEN, null) ?: return null
        val token = decrypt(encryptedToken) ?: return null
        return SyncEndpointValidator.validateOrNull(endpoint, token)
    }

    fun save(endpoint: String, bearerToken: String) {
        val config = SyncEndpointValidator.validate(endpoint, bearerToken)
        preferences.edit()
            .putString(KEY_ENDPOINT, config.endpoint)
            .putString(KEY_TOKEN, encrypt(config.bearerToken))
            .apply()
    }

    fun clear() {
        preferences.edit().clear().apply()
    }

    private fun encrypt(plaintext: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val iv = cipher.iv
        val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(
            ByteBuffer.allocate(INT_BYTES + iv.size + ciphertext.size)
                .putInt(iv.size)
                .put(iv)
                .put(ciphertext)
                .array(),
            Base64.NO_WRAP,
        )
    }

    private fun decrypt(encoded: String): String? = runCatching {
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val buffer = ByteBuffer.wrap(bytes)
        val ivLength = buffer.int
        require(ivLength in MIN_IV_BYTES..MAX_IV_BYTES)
        require(buffer.remaining() > ivLength)
        val iv = ByteArray(ivLength).also(buffer::get)
        val ciphertext = ByteArray(buffer.remaining()).also(buffer::get)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(GCM_TAG_BITS, iv))
        String(cipher.doFinal(ciphertext), Charsets.UTF_8)
    }.getOrNull()

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val existing = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
        if (existing != null) return existing
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(KEY_SIZE_BITS)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        const val PREFERENCES = "tracky_sync_configuration"
        const val KEY_ENDPOINT = "endpoint"
        const val KEY_TOKEN = "encrypted_bearer_token"
        const val KEY_ALIAS = "tracky_sync_token_v1"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val KEY_SIZE_BITS = 256
        const val GCM_TAG_BITS = 128
        const val INT_BYTES = 4
        const val MIN_IV_BYTES = 12
        const val MAX_IV_BYTES = 16
    }
}
