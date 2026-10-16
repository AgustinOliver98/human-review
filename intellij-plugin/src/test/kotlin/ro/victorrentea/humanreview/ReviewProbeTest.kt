package ro.victorrentea.humanreview

import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

// The status-bar decision (ReviewProbe.probeFolder) against a temp checkout, with the process
// table, the marker and git stubbed: grey/amber/green, and the marker asked once per (port, pid).
class ReviewProbeTest {
    private val folder: Path = Files.createTempDirectory("hr-probe")
    private val dir: Path = Files.createDirectories(folder.resolve(".human-review"))
    private val real = dir.toRealPath().toString()

    private fun page(sha: String = "abc12345", title: String = "Owners &amp; pets") = Files.writeString(
        dir.resolve("review.html"),
        """<!doctype html><html lang="en" data-hr-head="$sha" data-hr-branch="test-pr"><head><title>$title</title>""",
    )

    private fun served(port: Int = 7654, pid: Long = 999) =
        Files.writeString(dir.resolve(".server.json"), """{"port": $port, "pid": $pid}""")

    private fun marker(served: String = real, pid: Long = 999) = MarkerAnswer(true, JsonObject().apply {
        addProperty("humanReview", 1)
        addProperty("served", served)
        addProperty("pid", pid)
    }, answered = true)

    private val atReviewed: (String) -> Checkout? = { Checkout("abc12345ffff", "test-pr") }

    @Test fun `no review html - hidden`() {
        assertEquals(ReviewState.NONE, ReviewProbe.probeFolder(folder.toString()).state)
    }

    @Test fun `the stamp is read from the head of the page`() {
        page()
        val s = ReviewProbe.readStamp(dir.resolve("review.html"))!!
        assertEquals("abc12345", s.sha)
        assertEquals("test-pr", s.branch)
        assertEquals("Owners & pets", s.title)
    }

    @Test fun `a review with no server file is grey`() {
        page()
        val p = ReviewProbe.probeFolder(folder.toString(), marker = { error("must not ask") })
        assertEquals(ReviewState.OFF, p.state)
        assertEquals("Owners & pets", p.title)
    }

    @Test fun `a server file whose pid is dead is grey, without a network call`() {
        page(); served()
        val p = ReviewProbe.probeFolder(folder.toString(), alive = { false }, marker = { error("must not ask") })
        assertEquals(ReviewState.OFF, p.state)
    }

    @Test fun `served on the reviewed commit is green, with the page url`() {
        page(); served()
        val p = ReviewProbe.probeFolder(folder.toString(), alive = { true }, marker = { marker() }, head = atReviewed)
        assertEquals(ReviewState.ON, p.state)
        assertEquals("http://127.0.0.1:7654/review.html", p.url)
        assertEquals(999L, p.pid)
    }

    @Test fun `served on another commit is amber`() {
        page(); served()
        val p = ReviewProbe.probeFolder(folder.toString(), alive = { true }, marker = { marker() },
            head = { Checkout("deadbeef0000", "main") })
        assertEquals(ReviewState.NEAR, p.state)
        assertEquals("main", p.checkout!!.branch)
    }

    @Test fun `a page with no stamp counts as on the reviewed commit`() {
        page(sha = ""); served()
        val p = ReviewProbe.probeFolder(folder.toString(), alive = { true }, marker = { marker() }, head = { null })
        assertEquals(ReviewState.ON, p.state)
    }

    @Test fun `the marker is asked once per port and pid, then only the pid is checked`() {
        page(); served()
        val memo = ProbeMemo()
        var asked = 0
        repeat(3) {
            ReviewProbe.probeFolder(folder.toString(), memo, alive = { true }, marker = { asked++; marker() }, head = atReviewed)
        }
        assertEquals(1, asked)
        served(port = 7655)  // a restarted server: a new key, asked again
        ReviewProbe.probeFolder(folder.toString(), memo, alive = { true }, marker = { asked++; marker() }, head = atReviewed)
        assertEquals(2, asked)
    }

    @Test fun `someone else on the port is grey and never asked again`() {
        page(); served()
        val memo = ProbeMemo()
        var asked = 0
        val stranger = { _: Int -> asked++; MarkerAnswer(false, answered = true) }
        repeat(2) {
            assertEquals(ReviewState.OFF, ReviewProbe.probeFolder(folder.toString(), memo, alive = { true }, marker = stranger).state)
        }
        assertEquals(1, asked)
    }

    @Test fun `a server for another directory or pid is not ours`() {
        page(); served()
        assertEquals(ReviewState.OFF, ReviewProbe.probeFolder(folder.toString(), alive = { true },
            marker = { marker(served = "/elsewhere/.human-review") }).state)
        assertEquals(ReviewState.OFF, ReviewProbe.probeFolder(folder.toString(), alive = { true },
            marker = { marker(pid = 1) }).state)
    }

    @Test fun `nothing answering is grey but asked again next time`() {
        page(); served()
        val memo = ProbeMemo()
        var asked = 0
        repeat(2) {
            ReviewProbe.probeFolder(folder.toString(), memo, alive = { true }, marker = { asked++; MarkerAnswer(false) })
        }
        assertEquals(2, asked)
    }

    @Test fun `the most lit folder of a project wins`() {
        val states = mapOf("/a" to ReviewState.OFF, "/b" to ReviewState.ON, "/c" to ReviewState.NONE)
        val best = ReviewProbe.probeFolders(states.keys.toList(), ProbeMemo()) { f, _ -> Probe(states.getValue(f), f) }
        assertEquals("/b", best.folder)
        assertEquals(ReviewState.NONE, ReviewProbe.probeFolders(emptyList(), ProbeMemo()).state)
    }

    @Test fun `the configured script wins, then the installed plugin, then the cache, then a checkout`() {
        val home = Files.createTempDirectory("hr-home")
        val rel = "skills/human-review/scripts/serve-review.py"
        fun touch(p: Path) = p.also { Files.createDirectories(it.parent); Files.writeString(it, "") }
        assertNull(ReviewProbe.serveScript("", home.toString()))

        val checkout = touch(home.resolve("workspace/human-review/$rel"))
        assertEquals(checkout.toString(), ReviewProbe.serveScript("", home.toString()))

        val cached = touch(home.resolve(".claude/plugins/cache/human-review/human-review/abc/$rel"))
        assertEquals(cached.toString(), ReviewProbe.serveScript(null, home.toString()))

        val installed = touch(home.resolve("plugin-root/$rel"))
        Files.writeString(home.resolve(".claude/plugins/installed_plugins.json"),
            """{"plugins": {"human-review@human-review": [{"installPath": "${home.resolve("plugin-root")}"}]}}""")
        assertEquals(installed.toString(), ReviewProbe.serveScript(null, home.toString()))

        val mine = touch(home.resolve("mine.py"))
        assertEquals(mine.toString(), ReviewProbe.serveScript(mine.toString(), home.toString()))
        // a configured path that does not exist falls through to discovery
        assertEquals(installed.toString(), ReviewProbe.serveScript("/nope/serve-review.py", home.toString()))
    }

    @Test fun `python3 is found on the given PATH before the fallbacks`() {
        val bin = Files.createTempDirectory("hr-bin")
        val py = bin.resolve("python3")
        Files.writeString(py, "#!/bin/sh\n")
        py.toFile().setExecutable(true)
        assertEquals(py.toString(), ReviewProbe.python(bin.toString()))
        assertTrue(ReviewProbe.python("").endsWith("python3"))
    }
}
