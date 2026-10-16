package ro.victorrentea.humanreview

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

// review-open.js `locate`: a window qualifies only when the file at its HEAD is the very blob
// the review quoted — per file, not per commit.
class ReviewLocateTest {
    private val built = TestRepo().apply { write("src/A.java", "one\n"); write("B.txt", "b\n") }
    private val sha = built.commit("one")

    private fun win(key: String, app: String, vararg repos: TestRepo) = Window(key, app, repos.map { it.folder() })

    private fun clone(): TestRepo {
        val c = TestRepo(kotlin.io.path.createTempDirectory("hr-clone").toRealPath().resolve("c"))
        return c
    }

    @Test fun `the window on the reviewed blob wins, and says where`() {
        val got = ReviewLocate.locate("${built.dir}/src/A.java", sha, built.dir.toString(), "feature",
            listOf(win("here", "idea", built)))
        got as Located.Found
        assertEquals("here", got.hit.window.key)
        assertEquals("${built.dir}/src/A.java", got.hit.target)
        assertFalse(got.edited)
        assertEquals(sha.take(8), got.short)
    }

    @Test fun `a commit that does not touch the file still qualifies, one that does not`() {
        built.write("B.txt", "b2\n")
        built.commit("two")
        assertTrue(ReviewLocate.locate("${built.dir}/src/A.java", sha, built.dir.toString(), "",
            listOf(win("w", "idea", built))) is Located.Found)
        built.write("src/A.java", "moved\n")
        built.commit("three")
        assertTrue(ReviewLocate.locate("${built.dir}/src/A.java", sha, built.dir.toString(), "",
            listOf(win("w", "idea", built))) is Located.NoWindow)
    }

    @Test fun `an uncommitted edit still qualifies, marked edited`() {
        built.write("src/A.java", "one, edited\n")
        val got = ReviewLocate.locate("${built.dir}/src/A.java", sha, built.dir.toString(), "",
            listOf(win("w", "idea", built))) as Located.Found
        assertTrue(got.edited)
        assertEquals("⚠ Edited since the reviewed commit ${sha.take(8)}: lines may have moved",
            ReviewLocate.editedText(got.short))
    }

    @Test fun `another checkout at the same blob is found through the relative path`() {
        val other = TestRepo(kotlin.io.path.createTempDirectory("hr-other").toRealPath())
        other.write("src/A.java", "one\n")
        other.commit("same content, other history")
        built.write("src/A.java", "moved on\n")
        built.commit("moved")
        val got = ReviewLocate.locate("${built.dir}/src/A.java", sha, built.dir.toString(), "",
            listOf(win("built", "idea", built), win("other", "vscode", other))) as Located.Found
        assertEquals("other", got.hit.window.key)
        assertEquals("${other.dir}/src/A.java", got.hit.target)
    }

    @Test fun `IntelliJ's own window wins a tie with VS Code's`() {
        val got = ReviewLocate.locate("${built.dir}/src/A.java", sha, built.dir.toString(), "",
            listOf(win("vsc", "vscode", built), win("ij", "idea", built))) as Located.Found
        assertEquals("ij", got.hit.window.key)
    }

    @Test fun `bad requests`() {
        val w = listOf(win("w", "idea", built))
        assertEquals(Located.BadRequest, ReviewLocate.locate("${built.dir}/src/A.java", "", built.dir.toString(), "", w))
        assertEquals(Located.BadRequest, ReviewLocate.locate("${built.dir}/src/A.java", "zzzzzzz", built.dir.toString(), "", w))
        assertEquals(Located.BadRequest, ReviewLocate.locate("src/A.java", sha, built.dir.toString(), "", w))
        assertEquals(Located.BadRequest, ReviewLocate.locate("/elsewhere/A.java", sha, built.dir.toString(), "", w))
    }

    @Test fun `no window - the message and the prompt, in review-open-js words`() {
        built.write("src/A.java", "moved\n")
        built.commit("moved")
        val head = built.git("rev-parse", "--short=8", "HEAD")
        val got = ReviewLocate.locate("${built.dir}/src/A.java", sha, built.dir.toString(), "test-pr",
            listOf(win("w", "idea", built))) as Located.NoWindow
        assertEquals("No open IntelliJ window is on this commit (test-pr @ ${sha.take(8)})", got.message)
        assertEquals(listOf(
            "I'm reviewing src/A.java at commit $sha (branch test-pr), but no open IntelliJ window has that version of the file.",
            "Open IntelliJ windows: ${built.dir.fileName} (feature @ $head).",
            "Find a local checkout of this repository whose HEAD is $sha — the review was built in ${built.dir} — " +
                "and open it in IntelliJ (`open -a \"IntelliJ IDEA\" <dir>`).",
            "Do not check out, switch, reset or stash in any existing checkout: other sessions may be working in them. " +
                "If no checkout is at that commit, stop and tell me which one you would use.",
        ), got.prompt.lines())
    }

    @Test fun `the VS Code wording is the JS's, word for word`() {
        val got = ReviewLocate.noWindow("src/A.java", "abcdef1234", "main", "git@github.com:o/r.git", "/r",
            emptyList(), "VS Code", ReviewLocate.launchHint("vscode"))
        assertEquals("No open VS Code window is on this commit (main @ abcdef12)", got.message)
        assertEquals("I'm reviewing src/A.java at commit abcdef1234 (branch main, repo git@github.com:o/r.git), " +
            "but no open VS Code window has that version of the file.", got.prompt.lines()[0])
        assertEquals("Open VS Code windows: none.", got.prompt.lines()[1])
        assertTrue(got.prompt.lines()[2].endsWith("and open it in VS Code (`code <dir>`)."))
    }

    @Test fun `the refusal names the editors that were searched`() {
        assertEquals("IntelliJ", ReviewLocate.editorsNamed(setOf("idea"), "idea"))
        assertEquals("IntelliJ or VS Code", ReviewLocate.editorsNamed(setOf("vscode", "idea"), "idea"))
        assertEquals("VS Code", ReviewLocate.editorsNamed(setOf("vscode"), "idea"))
        assertEquals("IntelliJ", ReviewLocate.editorsNamed(emptySet(), "idea"))
    }
}
