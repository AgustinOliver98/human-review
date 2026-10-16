package ro.victorrentea.humanreview

import java.nio.file.Files
import java.nio.file.Path

/** A throwaway git checkout for the tests that need real blobs. */
class TestRepo(val dir: Path = Files.createTempDirectory("hr-repo").toRealPath()) {
    fun git(vararg args: String): String {
        val p = ProcessBuilder(listOf("git", "-C", dir.toString()) + args).redirectErrorStream(true).start()
        val out = p.inputStream.bufferedReader().readText()
        check(p.waitFor() == 0) { "git ${args.joinToString(" ")}: $out" }
        return out.trim()
    }

    init {
        git("init", "-q", "-b", "feature")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
    }

    fun write(rel: String, text: String): Path =
        dir.resolve(rel).also { Files.createDirectories(it.parent); Files.writeString(it, text) }

    fun commit(msg: String): String {
        git("add", "-A")
        git("commit", "-qm", msg)
        return git("rev-parse", "HEAD")
    }

    fun folder() = Folders.of(dir.toString())
}
