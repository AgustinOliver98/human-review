package ro.victorrentea.humanreview

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PageTargetTest {
    @Test
    fun `the tool window only when wanted and JCEF is there`() {
        assertEquals(PageTarget.TOOL_WINDOW, ReviewPage.target(inIde = true, jcef = true))
        assertEquals(PageTarget.BROWSER, ReviewPage.target(inIde = true, jcef = false))
        assertEquals(PageTarget.BROWSER, ReviewPage.target(inIde = false, jcef = true))
        assertEquals(PageTarget.BROWSER, ReviewPage.target(inIde = false, jcef = false))
    }

    @Test
    fun `a page loads from http or https, nothing else`() {
        assertTrue(ReviewPage.isHttp("http://127.0.0.1:8765/review.html"))
        assertTrue(ReviewPage.isHttp("HTTPS://x"))
        assertFalse(ReviewPage.isHttp("file:///tmp/review.html"))
        assertFalse(ReviewPage.isHttp(" http://x"))
        assertFalse(ReviewPage.isHttp("javascript:alert(1)"))
    }

    @Test
    fun `only a GitHub pull request comment is handed to the browser`() {
        assertTrue(CommentNotice.usable("https://github.com/o/r/pull/53#discussion_r1"))
        assertTrue(CommentNotice.usable("https://github.com/o/r/pull/53"))
        assertFalse(CommentNotice.usable("http://github.com/o/r/pull/53"))
        assertFalse(CommentNotice.usable("https://github.com.evil/o/r/pull/53"))
        assertFalse(CommentNotice.usable("https://github.com/o/r/issues/53"))
        assertFalse(CommentNotice.usable(null))
    }

    @Test
    fun `a link's comment parameters parse`() {
        val r = Links.parse("open", mapOf("file" to "/a/B.java", "line" to "7", "comment" to "1", "commentLine" to "9",
            "commentUrl" to "https://github.com/o/r/pull/1#discussion_r2")) as LinkRequest.Open
        assertEquals(CommentAim(9, "https://github.com/o/r/pull/1#discussion_r2"), r.comment)
        assertEquals(null, (Links.parse("open", mapOf("file" to "/a/B.java", "comment" to "0")) as LinkRequest.Open).comment)
        val ro = Links.parse("review-open", mapOf("file" to "/a/B.java", "line" to "4", "comment" to "true")) as LinkRequest.ReviewOpen
        assertEquals(CommentAim(4, null), ro.ref.commentAim(4))
    }
}
