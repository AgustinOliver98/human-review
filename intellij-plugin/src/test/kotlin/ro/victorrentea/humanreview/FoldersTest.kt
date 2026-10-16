package ro.victorrentea.humanreview

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

// Which project owns a path: longest prefix over both spellings, the same rule serve-review.py
// applies across editors, applied by the bridge across the project windows of one IDE.
class FoldersTest {
    private fun f(path: String, real: String = path) = Folder(path.substringAfterLast('/'), path, real)

    @Test fun `inside is a path prefix, not a string prefix`() {
        assertTrue(Folders.inside("/w/shop/A.java", "/w/shop"))
        assertTrue(Folders.inside("/w/shop", "/w/shop"))
        assertTrue(Folders.inside("/w/shop/A.java", "/w/shop/"))
        assertFalse(Folders.inside("/w/shop-clone/A.java", "/w/shop"))
        assertFalse(Folders.inside("/w/shop/A.java", ""))
    }

    @Test fun `the deepest folder wins across projects`() {
        val entries = listOf("parent" to f("/w"), "shop" to f("/w/shop"), "other" to f("/x"))
        assertEquals("shop", Folders.owner("/w/shop/src/A.java", null, entries))
        assertEquals("parent", Folders.owner("/w/notes.md", null, entries))
        assertNull(Folders.owner("/elsewhere/A.java", null, entries))
    }

    @Test fun `a content root outside the base path still owns its files`() {
        val entries = listOf("shop" to f("/w/shop"), "shop" to f("/libs/shared"), "lib" to f("/libs"))
        assertEquals("shop", Folders.owner("/libs/shared/B.java", null, entries))
    }

    @Test fun `a symlinked folder owns the file under either spelling`() {
        val entries = listOf("link" to f("/Users/v/ws/shop", "/Volumes/data/shop"), "x" to f("/Users/v"))
        assertEquals("link", Folders.owner("/Volumes/data/shop/A.java", null, entries))
        assertEquals("link", Folders.owner("/Users/v/ws/shop/A.java", null, entries))
        // the caller holds the link, the project was opened on the real path
        val real = listOf("real" to f("/Volumes/data/shop"))
        assertEquals("real", Folders.owner("/Users/v/ws/shop/A.java", "/Volumes/data/shop/A.java", real))
    }

    @Test fun `folders are listed once`() {
        val out = Folders.dedupe(listOf(f("/w/shop"), f("/w/shop"), f("/w/lib")))
        assertEquals(listOf("/w/shop", "/w/lib"), out.map { it.path })
    }

    @Test fun `a folder carries its realpath`() {
        val dir = Files.createTempDirectory("hr-real")
        val link = dir.resolveSibling(dir.fileName.toString() + "-link")
        Files.createSymbolicLink(link, dir)
        try {
            val folder = Folders.of(link.toString())
            assertEquals(link.toString(), folder.path)
            assertEquals(dir.toRealPath().toString(), folder.realPath)
            assertEquals(link.fileName.toString(), folder.name)
        } finally {
            Files.deleteIfExists(link)
            Files.deleteIfExists(dir)
        }
    }
}
