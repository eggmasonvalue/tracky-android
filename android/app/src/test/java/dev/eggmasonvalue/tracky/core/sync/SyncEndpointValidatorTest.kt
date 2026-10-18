package dev.eggmasonvalue.tracky.core.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class SyncEndpointValidatorTest {
    @Test
    fun `accepts HTTPS endpoint and keeps token out of config string`() {
        val config = SyncEndpointValidator.validate(" https://appliance.example/ ", "test-token")

        assertEquals("https://appliance.example", config.endpoint)
        assertEquals("test-token", config.bearerToken)
        assertEquals("SyncEndpointConfig(endpoint=https://appliance.example, bearerToken=<redacted>)", config.toString())
    }

    @Test
    fun `rejects cleartext credentials queries fragments and whitespace`() {
        listOf(
            "http://appliance.example",
            "https://user:password@appliance.example",
            "https://appliance.example?token=secret",
            "https://appliance.example/#fragment",
            "https://appliance example",
        ).forEach { endpoint ->
            assertThrows(IllegalArgumentException::class.java) {
                SyncEndpointValidator.validate(endpoint, "test-token")
            }
        }
        assertThrows(IllegalArgumentException::class.java) {
            SyncEndpointValidator.validate("https://appliance.example", "token with spaces")
        }
    }

    @Test
    fun `missing configuration is represented as null`() {
        assertEquals(null, SyncEndpointValidator.validateOrNull(null, "test-token"))
        assertEquals(null, SyncEndpointValidator.validateOrNull("http://localhost", "test-token"))
    }
}
