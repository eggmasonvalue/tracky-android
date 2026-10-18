package dev.eggmasonvalue.tracky.core.sync

import java.io.BufferedInputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

interface ObservationTransport {
    suspend fun fetch(config: SyncEndpointConfig, cursor: String?): ObservationPage
}

/** Small, dependency-free HTTPS transport with bounded responses and no token logging. */
class HttpObservationTransport : ObservationTransport {
    override suspend fun fetch(config: SyncEndpointConfig, cursor: String?): ObservationPage =
        withContext(Dispatchers.IO) {
            val endpoint = buildEndpoint(config.endpoint, cursor)
            val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = TIMEOUT_MILLIS
                readTimeout = TIMEOUT_MILLIS
                instanceFollowRedirects = false
                setRequestProperty("Accept", "application/json")
                setRequestProperty("Authorization", "Bearer ${config.bearerToken}")
            }
            try {
                when (val status = connection.responseCode) {
                    HttpURLConnection.HTTP_OK -> {
                        val contentLength = connection.getHeaderFieldLong("Content-Length", -1L)
                        if (contentLength > MAX_RESPONSE_BYTES) {
                            throw SyncTransportException(
                                retryable = false,
                                code = "response_too_large",
                                message = "Sync response exceeds the configured size limit",
                            )
                        }
                        val body = readBounded(connection)
                        try {
                            ObservationPageParser.parse(body)
                        } catch (error: ObservationContractException) {
                            throw SyncTransportException(
                                retryable = true,
                                code = "invalid_observation_response",
                                message = error.message ?: "Invalid observation response",
                            )
                        }
                    }
                    HttpURLConnection.HTTP_UNAUTHORIZED,
                    HttpURLConnection.HTTP_FORBIDDEN,
                    -> throw SyncTransportException(
                        retryable = false,
                        code = "authentication_failed",
                        message = "The sync endpoint rejected the configured credentials",
                    )
                    HttpURLConnection.HTTP_BAD_REQUEST,
                    HttpURLConnection.HTTP_NOT_FOUND,
                    -> throw SyncTransportException(
                        retryable = false,
                        code = "endpoint_rejected_request",
                        message = "The sync endpoint rejected the configured request",
                    )
                    else -> throw SyncTransportException(
                        retryable = status == HTTP_TOO_MANY_REQUESTS || status >= 500,
                        code = if (status == HTTP_TOO_MANY_REQUESTS) {
                            "endpoint_rate_limited"
                        } else {
                            "endpoint_unavailable"
                        },
                        message = "The sync endpoint returned an unexpected status",
                    )
                }
            } finally {
                connection.disconnect()
            }
        }

    private fun buildEndpoint(base: String, cursor: String?): String {
        val baseUri = URI(base)
        val basePath = baseUri.path.trimEnd('/')
        val route = if (basePath.endsWith(API_PATH)) {
            baseUri.toString()
        } else {
            baseUri.toString().trimEnd('/') + API_PATH
        }
        return if (cursor.isNullOrBlank()) {
            route
        } else {
            route + "?cursor=" + URLEncoder.encode(cursor, StandardCharsets.UTF_8.name())
        }
    }

    private fun readBounded(connection: HttpURLConnection): String {
        val input = BufferedInputStream(connection.inputStream)
        val bytes = input.use { stream ->
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(8 * 1024)
            var total = 0
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                total += count
                if (total > MAX_RESPONSE_BYTES) {
                    throw SyncTransportException(
                        retryable = false,
                        code = "response_too_large",
                        message = "Sync response exceeds the configured size limit",
                    )
                }
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        return bytes.toString(StandardCharsets.UTF_8)
    }

    private companion object {
        const val TIMEOUT_MILLIS = 15_000
        const val HTTP_TOO_MANY_REQUESTS = 429
        const val MAX_RESPONSE_BYTES = 1_048_576L
        const val API_PATH = "/api/v1/sessions/unsynced"
    }
}
