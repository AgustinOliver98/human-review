package ro.victorrentea.humanreview

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions

// The contract serve-review.py relies on: one owner-only `idea-<pid>.json` with app/port/token/pid,
// and a token check that lets nothing else through.
class RegistryTest {
    @Test fun `the entry says idea, port, token, pid - numbers as numbers`() {
        val o = JsonParser.parseString(Registry.json(51234, "abc123", 4242L)).asJsonObject
        assertEquals("idea", o["app"].asString)
        assertTrue(o["port"].asJsonPrimitive.isNumber)
        assertEquals(51234, o["port"].asInt)
        assertEquals("abc123", o["token"].asString)
        assertEquals(4242L, o["pid"].asLong)
        assertEquals(setOf("app", "port", "token", "pid"), o.keySet())
    }

    @Test fun `published owner-only, under idea-pid, replacing a stale one`() {
        val dir = Files.createTempDirectory("hr-ide").resolve("nested")
        val first = Registry.publish(dir, 1, "old", 77L)
        val file = Registry.publish(dir, 2, "new", 77L)
        assertEquals(first, file)
        assertEquals("idea-77.json", file.fileName.toString())
        assertEquals("rw-------", PosixFilePermissions.toString(Files.getPosixFilePermissions(file)))
        assertEquals("new", JsonParser.parseString(Files.readString(file)).asJsonObject["token"].asString)
    }

    @Test fun `tokens are 32 hex chars and never repeat`() {
        val a = Token.mint()
        assertTrue(a.matches(Regex("[0-9a-f]{32}")))
        assertFalse(a == Token.mint())
    }

    @Test fun `only the exact token passes`() {
        assertTrue(Token.ok("abc", "abc"))
        assertFalse(Token.ok("abc", "abd"))
        assertFalse(Token.ok("abc", "ab"))
        assertFalse(Token.ok("abc", null))
        assertFalse(Token.ok("abc", ""))
        assertFalse(Token.ok(null, null))  // not started: nothing passes
        assertFalse(Token.ok("", ""))
    }
}
