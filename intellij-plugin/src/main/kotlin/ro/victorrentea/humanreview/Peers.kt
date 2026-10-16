package ro.victorrentea.humanreview

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.URI
import java.nio.file.Files
import java.nio.file.Path

// The other editors running a Human Review bridge on this machine: every `vscode-<pid>.json`
// and `idea-<pid>.json` under ~/.human-review/ide/ (Registry.kt). A click that reached this IDE
// — through `/review-open` or a `jetbrains://` link — may belong in one of them, and is then
// handed over on its port, with its token, exactly as serve-review.py would have.

/** One registry entry: who to ask, and how. */
data class Peer(val app: String, val port: Int, val token: String, val pid: Long, val file: Path?)

/** A peer that answered `/ping`, with the folders it owns. */
data class LivePeer(val peer: Peer, val folders: List<Folder>, val folder: String?)

object Peers {
    private val NAME = Regex("""^(vscode|idea)-\d+\.json$""")

    /** A registry file's entry, or null for anything that is not one. `app` defaults to the
     *  file's prefix: a bridge too old to say is the editor its file is named after. */
    fun parse(name: String, text: String, file: Path? = null): Peer? {
        val m = NAME.matchEntire(name) ?: return null
        val o = runCatching { JsonParser.parseString(text).asJsonObject }.getOrNull() ?: return null
        val port = o.num("port")?.toInt() ?: return null
        val token = o.get("token")?.takeIf { it.isJsonPrimitive }?.asString ?: return null
        val pid = o.num("pid")?.toLong() ?: return null
        val app = o.get("app")?.takeIf { it.isJsonPrimitive }?.asString ?: m.groupValues[1]
        return Peer(app, port, token, pid, file)
    }

    private fun JsonObject.num(k: String): Double? =
        get(k)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.asDouble

    /** Every entry, sorted by file name (VS Code's before IntelliJ's, as serve-review.py does). */
    fun entries(dir: Path = Registry.DIR): List<Peer> = runCatching {
        Files.list(dir).use { s -> s.toList() }
            .sortedWith(compareBy({ !it.fileName.toString().startsWith("vscode-") }, { it.fileName.toString() }))
            .mapNotNull { f -> runCatching { parse(f.fileName.toString(), Files.readString(f), f) }.getOrNull() }
    }.getOrDefault(emptyList())

    fun self(p: Peer) = p.pid == ProcessHandle.current().pid()

    /** `(status, body)`, or null when nothing answered. A refused port deletes the entry:
     *  that is proof the editor is gone. A timeout proves nothing and deletes nothing, because
     *  unplugging a live window costs it until its next start. */
    fun call(p: Peer, method: String, route: String, body: Map<String, Any?>? = null, timeoutMs: Int = 4000): Pair<Int, JsonObject?>? {
        val conn = runCatching { URI("http://127.0.0.1:${p.port}$route").toURL().openConnection() as HttpURLConnection }
            .getOrNull() ?: return null
        return try {
            conn.requestMethod = method
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.setRequestProperty("x-relay-token", p.token)
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(Gson().toJson(body).toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val stream = if (code < 400) conn.inputStream else conn.errorStream
            val text = stream?.use { String(it.readNBytes(1 shl 20), Charsets.UTF_8) } ?: ""
            code to runCatching { JsonParser.parseString(text).asJsonObject }.getOrNull()
        } catch (_: ConnectException) {
            p.file?.let { runCatching { Files.deleteIfExists(it) } }
            null
        } catch (_: Exception) {
            null
        } finally {
            conn.disconnect()
        }
    }

    /** The peer's `/ping`, when it is a Human Review bridge that answers. */
    fun ping(p: Peer, timeoutMs: Int = 2000): LivePeer? {
        val (code, b) = call(p, "GET", "/ping", timeoutMs = timeoutMs) ?: return null
        if (code != 200 || b == null || b.get("ok")?.let { it.isJsonPrimitive && it.asBoolean } != true) return null
        val app = b.get("app")?.takeIf { it.isJsonPrimitive }?.asString ?: "vscode"
        if (app != "vscode" && app != "idea") return null
        val folders = b.get("folders")?.takeIf { it.isJsonArray }?.asJsonArray?.mapNotNull { e ->
            val o = e.takeIf { it.isJsonObject }?.asJsonObject ?: return@mapNotNull null
            fun s(k: String) = o.get(k)?.takeIf { it.isJsonPrimitive }?.asString
            val path = s("path") ?: return@mapNotNull null
            Folder(s("name") ?: path.substringAfterLast('/'), path, s("realPath") ?: path)
        } ?: emptyList()
        val folder = b.get("folder")?.takeIf { it.isJsonPrimitive }?.asString
        return LivePeer(p.copy(app = app), folders, folder)
    }

    /** Every other editor that answers, this process left out (it is asked directly). */
    fun live(registry: Path = Registry.DIR): List<LivePeer> = entries(registry).filter { !self(it) }.mapNotNull { ping(it) }

    /** The peer whose folders claim `file` most specifically, among `live` — or null. */
    fun ownerOf(file: String, live: List<LivePeer>): LivePeer? {
        val real = runCatching { Path.of(file).toRealPath().toString() }.getOrNull()
        return Folders.owner(file, real, live.flatMap { lp -> lp.folders.map { lp to it } })
    }
}
