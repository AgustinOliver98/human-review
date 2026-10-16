package ro.victorrentea.humanreview

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.intellij.diff.DiffDialogHints
import com.intellij.diff.DiffManager
import com.intellij.diff.DiffRequestPanel
import com.intellij.diff.chains.DiffRequestChain
import com.intellij.diff.contents.DocumentContent
import com.intellij.diff.merge.MergeRequest
import com.intellij.diff.requests.DiffRequest
import com.intellij.diff.requests.SimpleDiffRequest
import com.intellij.diff.util.DiffUserDataKeys
import com.intellij.diff.util.Side
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.JBProtocolCommand
import com.intellij.openapi.components.service
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.ex.FileEditorManagerEx
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.testFramework.HeavyPlatformTestCase
import com.intellij.testFramework.PlatformTestUtil
import com.intellij.testFramework.replaceService
import com.sun.net.httpserver.HttpServer
import kotlinx.coroutines.runBlocking
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.URI
import java.net.URLEncoder
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CopyOnWriteArrayList

/**
 * The IDE half, headless: a real project on disk with a git repository in it, the bridge
 * listening on loopback with its registry in a temporary directory, the diff viewer replaced by
 * a recorder, and no window raised (Ide.raise is a no-op in a test run). The test runs on the
 * EDT; what the bridge's callers do runs on a pooled thread (`offEdt`), as it does in the IDE,
 * while the EDT keeps dispatching the work they hand it.
 */
class HeadlessIdeTest : HeavyPlatformTestCase() {
    private fun <T> offEdt(block: () -> T): T =
        PlatformTestUtil.waitForFuture(ApplicationManager.getApplication().executeOnPooledThread<T> { block() }, 60_000)

    private lateinit var registry: Path
    private lateinit var repo: TestRepo
    private lateinit var base: String
    private val diffs = CopyOnWriteArrayList<DiffRequest>()

    /** What `DiffManager.showDiff` was asked, instead of a diff window. */
    private inner class Recorder : DiffManager() {
        override fun showDiff(project: Project?, request: DiffRequest) { diffs += request }
        override fun showDiff(project: Project?, request: DiffRequest, hints: DiffDialogHints) { diffs += request }
        override fun showDiff(project: Project?, chain: DiffRequestChain, hints: DiffDialogHints) = error("not used")
        override fun createRequestPanel(project: Project?, parent: Disposable, window: java.awt.Window?): DiffRequestPanel = error("not used")
        override fun showMerge(project: Project?, request: MergeRequest) = error("not used")
    }

    override fun setUp() {
        super.setUp()
        registry = Files.createTempDirectory("hr-registry")
        System.setProperty("human-review.registry.dir", registry.toString())
        ApplicationManager.getApplication().replaceService(DiffManager::class.java, Recorder(), testRootDisposable)
        repo = TestRepo(Files.createDirectories(Path.of(project.basePath!!)).toRealPath())
        repo.write("src/Owner.java", (1..40).joinToString("\n") { "// line $it" } + "\n")
        repo.write("src/Same.java", "class Same {}\n")
        base = repo.commit("one")
        LocalFileSystem.getInstance().refreshAndFindFileByNioFile(repo.dir)?.let { it.refresh(false, true) }
    }

    override fun tearDown() {
        try {
            service<HumanReviewBridge>().stop()
            RangeFocus.clear()
            EditedMark.clear()
            FileEditorManagerEx.getInstanceEx(project).closeAllFiles()
        } catch (e: Throwable) {
            addSuppressedException(e)
        } finally {
            super.tearDown()
        }
    }

    private fun bridge(): Pair<Int, String> {
        val b = service<HumanReviewBridge>()
        b.start(registry)  // once per test JVM; later calls find it running
        return b.address()!!
    }

    private fun post(route: String, body: Map<String, Any?>): Pair<Int, JsonObject> = offEdt { postNow(route, body) }

    private fun postNow(route: String, body: Map<String, Any?>): Pair<Int, JsonObject> {
        val (port, token) = bridge()
        val c = URI("http://127.0.0.1:$port$route").toURL().openConnection() as HttpURLConnection
        c.requestMethod = "POST"
        c.doOutput = true
        c.connectTimeout = 5000
        c.readTimeout = 20000
        c.setRequestProperty("x-relay-token", token)
        c.setRequestProperty("Content-Type", "application/json")
        c.outputStream.use { it.write(Gson().toJson(body).toByteArray()) }
        val code = c.responseCode
        val text = (if (code < 400) c.inputStream else c.errorStream).use { String(it.readAllBytes()) }
        return code to JsonParser.parseString(text).asJsonObject
    }

    private fun path(rel: String) = repo.dir.resolve(rel).toString()

    private fun selectedFile(): String? = FileEditorManager.getInstance(project).selectedTextEditor?.virtualFile?.path

    // ------------------------------------------------------------------ /open-diff

    fun `test open-diff asks the diff viewer for the base on the left and the file on the right`() {
        repo.write("src/Owner.java", (1..40).joinToString("\n") { if (it == 30) "// changed" else "// line $it" } + "\n")
        val (code, body) = post("/open-diff", mapOf("file" to path("src/Owner.java"), "base" to base, "line" to 30, "focus" to true))
        assertEquals(body.toString(), 200, code)
        val req = diffs.single() as SimpleDiffRequest
        val short = base.take(8)
        assertEquals("Owner@$short.java ↔ Owner.java", req.title)
        assertEquals(listOf("Owner@$short.java", "Owner.java"), req.contentTitles)
        val (left, right) = req.contents.map { it as DocumentContent }
        assertTrue(left.document.text.contains("// line 30"))
        assertFalse("the base side is read-only", left.document.isWritable)
        assertTrue(right.document.text.contains("// changed"))
        assertTrue("the working tree side is editable", right.document.isWritable)
        assertEquals(path("src/Owner.java"), right.highlightFile?.path)
        val at = req.getUserData(DiffUserDataKeys.SCROLL_TO_LINE)!!
        assertEquals(Side.RIGHT, at.first)
        assertEquals(29, at.second)
    }

    fun `test open-diff refuses in diff-js words, as a 409`() {
        fun refusal(file: String, base: String) =
            post("/open-diff", mapOf("file" to file, "base" to base)).also { assertEquals(409, it.first) }.second["error"].asString
        assertEquals("Same.java is unchanged since ${base.take(8)}", refusal(path("src/Same.java"), base))
        assertEquals("not a usable git ref", refusal(path("src/Same.java"), "--upload-pack=x"))
        assertEquals("Same.java does not exist at nosuchre", refusal(path("src/Same.java"), "nosuchref"))
        assertEquals("that path is not in this window", refusal("/elsewhere/A.java", base))
        assertTrue(diffs.isEmpty())
    }

    // ------------------------------------------------------------------ /review-open

    fun `test review-open opens the reviewed version here, as a range`() {
        val (code, body) = post("/review-open", mapOf("file" to path("src/Owner.java"), "line" to 10, "endLine" to 12,
            "sha" to base, "root" to repo.dir.toString(), "branch" to "feature"))
        assertEquals(body.toString(), 200, code)
        assertEquals(path("src/Owner.java"), body["path"].asString)
        assertFalse(body["edited"].asBoolean)
        assertEquals(path("src/Owner.java"), selectedFile())
        assertEquals(mapOf("path" to path("src/Owner.java"), "line" to 10, "endLine" to 12), RangeFocus.active())
    }

    fun `test review-open says edited when the working tree moved on`() {
        repo.write("src/Owner.java", "// edited\n" + Files.readString(Path.of(path("src/Owner.java"))))
        val (code, body) = post("/review-open", mapOf("file" to path("src/Owner.java"), "line" to 3,
            "sha" to base, "root" to repo.dir.toString()))
        assertEquals(body.toString(), 200, code)
        assertTrue(body["edited"].asBoolean)
    }

    fun `test review-open with no window on the blob is a 409 with a prompt, and a bad sha a 400`() {
        repo.write("src/Owner.java", "moved on\n")
        repo.commit("two")
        val (code, body) = post("/review-open", mapOf("file" to path("src/Owner.java"), "line" to 3,
            "sha" to base, "root" to repo.dir.toString(), "branch" to "feature"))
        assertEquals(409, code)
        assertEquals("no-window", body["error"].asString)
        assertEquals("No open IntelliJ window is on this commit (feature @ ${base.take(8)})", body["message"].asString)
        assertTrue(body["prompt"].asString.contains("Find a local checkout of this repository whose HEAD is $base"))
        assertEquals(400, post("/review-open", mapOf("file" to path("src/Owner.java"), "sha" to "", "root" to repo.dir.toString())).first)
    }

    fun `test review-open hands over to the bridge whose checkout has the reviewed blob`() {
        // Another checkout at the reviewed content, open in a "VS Code window" that is only a stub
        // on loopback, registered in the test's own registry.
        val other = TestRepo(Files.createTempDirectory("hr-other").toRealPath())
        other.write("src/Owner.java", Files.readString(Path.of(path("src/Owner.java"))))
        other.commit("same content")
        repo.write("src/Owner.java", "moved on\n")
        repo.commit("two")
        val got = CopyOnWriteArrayList<JsonObject>()
        val stub = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
            createContext("/") { ex ->
                val reply = when (ex.requestURI.path) {
                    "/ping" -> Gson().toJson(mapOf("ok" to true, "app" to "vscode", "folder" to "other",
                        "folders" to listOf(mapOf("name" to "other", "path" to other.dir.toString(), "realPath" to other.dir.toString()))))
                    "/open-file" -> { got += JsonParser.parseString(String(ex.requestBody.readAllBytes())).asJsonObject; """{"ok":true}""" }
                    else -> """{"ok":false}"""
                }.toByteArray()
                ex.sendResponseHeaders(200, reply.size.toLong())
                ex.responseBody.use { it.write(reply) }
            }
            start()
        }
        try {
            Files.writeString(registry.resolve("vscode-999999.json"),
                """{"app":"vscode","port":${stub.address.port},"token":"t","pid":999999}""")
            val (code, body) = post("/review-open", mapOf("file" to path("src/Owner.java"), "line" to 5, "endLine" to 7,
                "sha" to base, "root" to repo.dir.toString()))
            assertEquals(body.toString(), 200, code)
            assertEquals("vscode", body["app"].asString)
            assertEquals("${other.dir}/src/Owner.java", got.single()["path"].asString)
            assertEquals(5, got.single()["line"].asInt)
            assertEquals(7, got.single()["endLine"].asInt)
        } finally {
            stub.stop(0)
            Files.deleteIfExists(registry.resolve("vscode-999999.json"))
        }
    }

    // ------------------------------------------------------------------ jetbrains://

    private fun q(s: String) = URLEncoder.encode(s, Charsets.UTF_8).replace("+", "%20")

    /** The platform's own entry for `jetbrains://<query>`: finds the command by the name
     *  registered in plugin.xml, parses target and parameters, runs it. */
    private fun link(query: String) = offEdt { runBlocking { JBProtocolCommand.execute(query) } }

    fun `test a jetbrains open link reaches the plugin through the protocol command EP`() {
        link("idea/human-review/open?file=${q(path("src/Owner.java"))}&line=20&endLine=23")
        assertEquals(path("src/Owner.java"), selectedFile())
        assertEquals(mapOf("path" to path("src/Owner.java"), "line" to 20, "endLine" to 23), RangeFocus.active())
    }

    fun `test a jetbrains diff link opens the diff, and a refused one the file`() {
        repo.write("src/Owner.java", "changed\n")
        link("idea/human-review/diff?file=${q(path("src/Owner.java"))}&base=$base&line=1")
        assertEquals("Owner@${base.take(8)}.java ↔ Owner.java", (diffs.single() as SimpleDiffRequest).title)
        link("idea/human-review/diff?file=${q(path("src/Same.java"))}&base=$base&line=1")
        assertEquals(1, diffs.size)
        assertEquals(path("src/Same.java"), selectedFile())
    }

    fun `test a jetbrains review-open link opens the reviewed version`() {
        link("idea/human-review/review-open?file=${q(path("src/Owner.java"))}&line=4&endLine=6&sha=$base" +
            "&root=${q(repo.dir.toString())}&branch=feature")
        assertEquals(mapOf("path" to path("src/Owner.java"), "line" to 4, "endLine" to 6), RangeFocus.active())
    }
}
