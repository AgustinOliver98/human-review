package ro.victorrentea.humanreview

import com.google.gson.Gson
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardOpenOption
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import java.security.SecureRandom

// Where every editor running a Human Review bridge publishes `{port, token, pid}`, one file per
// process. VS Code writes `vscode-<pid>.json` (one per extension host, i.e. per window); this
// plugin writes `idea-<pid>.json` — ONE per IDE process, because IntelliJ hosts every project
// window in the same JVM. serve-review.py reads the directory to find the editor that owns a
// file.
//
// Its own directory, not the `~/.walkie-talkie/ide/` the live-coding plugin publishes its relay
// listener in: both plugins can run in the same IDE, and one pid means one file name — sharing a
// directory, each would overwrite the other's token.
object Registry {
    /** `-Dhuman-review.registry.dir=…` moves it: the tests publish and look up bridges in a
     *  temporary directory, so nothing they start is ever routed to, and nothing they hand over
     *  can reach an editor someone is working in. */
    val DIR: Path
        get() = System.getProperty("human-review.registry.dir")?.takeIf { it.isNotBlank() }?.let { Path.of(it) }
            ?: Path.of(System.getProperty("user.home"), ".human-review", "ide")

    fun fileName(pid: Long) = "idea-$pid.json"

    fun json(port: Int, token: String, pid: Long): String =
        Gson().toJson(linkedMapOf("app" to "idea", "port" to port, "token" to token, "pid" to pid))

    /** Write the entry readable by its owner only. The file is created 0600 *before* the token
     *  goes in, so there is no moment it sits world-readable with the secret inside. */
    fun publish(dir: Path, port: Int, token: String, pid: Long): Path {
        Files.createDirectories(dir)
        val file = dir.resolve(fileName(pid))
        Files.deleteIfExists(file)
        val owner = PosixFilePermissions.fromString("rw-------")
        runCatching { Files.createFile(file, PosixFilePermissions.asFileAttribute(owner)) }
            .onFailure { Files.createFile(file) }  // not a POSIX filesystem
        Files.writeString(file, json(port, token, pid), StandardOpenOption.TRUNCATE_EXISTING)
        runCatching { Files.setPosixFilePermissions(file, owner) }
        return file
    }
}

object Token {
    /** A shared secret in a 0600 file in the user's home: any local process can reach a
     *  loopback port, and this one opens files and raises windows. */
    fun mint(): String = ByteArray(16).also { SecureRandom().nextBytes(it) }
        .joinToString("") { "%02x".format(it) }

    /** Constant-time, so the comparison does not tell a caller how much of a guess was right. */
    fun ok(expected: String?, got: String?): Boolean =
        !expected.isNullOrEmpty() && got != null &&
            MessageDigest.isEqual(expected.toByteArray(), got.toByteArray())
}
