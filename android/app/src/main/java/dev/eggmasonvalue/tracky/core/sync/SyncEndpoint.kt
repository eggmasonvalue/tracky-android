package dev.eggmasonvalue.tracky.core.sync

import java.net.URI

/** Endpoint and bearer token held only in memory by the sync operation. */
class SyncEndpointConfig internal constructor(
    val endpoint: String,
    val bearerToken: String,
) {
    override fun toString(): String = "SyncEndpointConfig(endpoint=$endpoint, bearerToken=<redacted>)"
}

object SyncEndpointValidator {
    fun validate(endpoint: String, bearerToken: String): SyncEndpointConfig {
        val normalizedEndpoint = endpoint.trim().trimEnd('/')
        require(normalizedEndpoint.length in 1..2048) { "Endpoint must be between 1 and 2048 characters" }
        val uri = try {
            URI(normalizedEndpoint)
        } catch (_: Exception) {
            throw IllegalArgumentException("Endpoint is not a valid URL")
        }
        require(uri.scheme.equals("https", ignoreCase = true)) {
            "Endpoint must use HTTPS; configure a trusted HTTPS tunnel for local access"
        }
        require(uri.userInfo == null) { "Endpoint must not contain URL credentials" }
        require(uri.host != null && uri.host.isNotBlank()) { "Endpoint must include a host" }
        require(uri.query == null && uri.fragment == null) {
            "Endpoint must not contain a query or fragment"
        }
        require(normalizedEndpoint.none(Char::isISOControl) && !normalizedEndpoint.any(Char::isWhitespace)) {
            "Endpoint must not contain whitespace or control characters"
        }
        require(bearerToken.length in 1..4096) { "Bearer token must be between 1 and 4096 characters" }
        require(bearerToken.none(Char::isISOControl) && !bearerToken.any(Char::isWhitespace)) {
            "Bearer token must not contain whitespace or control characters"
        }
        return SyncEndpointConfig(normalizedEndpoint, bearerToken)
    }

    fun validateOrNull(endpoint: String?, bearerToken: String?): SyncEndpointConfig? =
        if (endpoint == null || bearerToken == null) {
            null
        } else {
            runCatching { validate(endpoint, bearerToken) }.getOrNull()
        }
}

interface SyncConfigSource {
    fun load(): SyncEndpointConfig?
}
