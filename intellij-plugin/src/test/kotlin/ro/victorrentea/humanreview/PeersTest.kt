package ro.victorrentea.humanreview

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.nio.file.Files

// The registry as the other bridges write it: `vscode-<pid>.json` (with `ppid`, sometimes no
// `app`) and `idea-<pid>.json`.
class PeersTest {
    @Test fun `both editors' entries parse, app defaulting to the file's prefix`() {
        assertEquals(Peer("vscode", 5000, "t", 42, null),
            Peers.parse("vscode-42.json", """{"app":"vscode","port":5000,"token":"t","pid":42,"ppid":1}"""))
        assertEquals(Peer("vscode", 5000, "t", 42, null), Peers.parse("vscode-42.json", """{"port":5000,"token":"t","pid":42}"""))
        assertEquals(Peer("idea", 6000, "u", 7, null), Peers.parse("idea-7.json", Registry.json(6000, "u", 7)))
    }

    @Test fun `anything else is not an entry`() {
        assertNull(Peers.parse("walkie-1.json", """{"port":1,"token":"t","pid":1}"""))
        assertNull(Peers.parse("idea-7.json", "not json"))
        assertNull(Peers.parse("idea-7.json", """{"token":"t","pid":7}"""))
        assertNull(Peers.parse("idea-7.json.tmp", Registry.json(1, "t", 7)))
    }

    @Test fun `entries are read sorted, VS Code's before IntelliJ's`() {
        val dir = Files.createTempDirectory("hr-peers")
        Files.writeString(dir.resolve("idea-1.json"), Registry.json(1, "a", 1))
        Files.writeString(dir.resolve("vscode-2.json"), """{"app":"vscode","port":2,"token":"b","pid":2}""")
        Files.writeString(dir.resolve("notes.txt"), "x")
        assertEquals(listOf("vscode", "idea"), Peers.entries(dir).map { it.app })
    }

    @Test fun `a refused port deletes its entry`() {
        val dir = Files.createTempDirectory("hr-peers")
        val file = dir.resolve("vscode-9.json")
        val free = java.net.ServerSocket(0).use { it.localPort }
        Files.writeString(file, """{"app":"vscode","port":$free,"token":"t","pid":9}""")
        val peer = Peers.entries(dir).single()
        assertNull(Peers.ping(peer))
        assertEquals(false, Files.exists(file))
    }
}
