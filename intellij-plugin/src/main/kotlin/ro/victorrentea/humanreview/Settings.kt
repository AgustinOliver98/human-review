package ro.victorrentea.humanreview

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.components.service
import com.intellij.openapi.options.Configurable
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.UIUtil
import com.intellij.util.ui.FormBuilder
import javax.swing.JComponent

/** `serveScript` — absolute path to `serve-review.py`, for the status-bar item to start a server
 *  with. Empty: the copy installed with the `human-review` Claude Code plugin, else
 *  `~/workspace/human-review`. The twin of VS Code's `humanReview.serveScript`.
 *
 *  `pageInIde` — where a click on the status-bar item opens the page: the Human Review tool
 *  window (true, the default, as VS Code opens it in its Simple Browser beside the code) or the
 *  OS browser. An IDE without JCEF uses the browser whatever this says (`ReviewPage.target`). */
@Service(Service.Level.APP)
@State(name = "HumanReviewSettings", storages = [Storage("human-review.xml")])
class HumanReviewSettings : PersistentStateComponent<HumanReviewSettings.Data> {
    class Data {
        var serveScript: String = ""
        var pageInIde: Boolean = true
    }

    private var data = Data()

    override fun getState(): Data = data
    override fun loadState(state: Data) {
        data = state
    }

    var serveScript: String
        get() = data.serveScript
        set(v) { data.serveScript = v.trim() }

    var pageInIde: Boolean
        get() = data.pageInIde
        set(v) { data.pageInIde = v }

    companion object {
        fun get(): HumanReviewSettings = service()
    }
}

/** Settings → Tools → Human Review. */
class HumanReviewConfigurable : Configurable {
    private var field: JBTextField? = null
    private var inIde: JBCheckBox? = null

    override fun getDisplayName() = "Human Review"

    override fun createComponent(): JComponent {
        val f = JBTextField(HumanReviewSettings.get().serveScript).also { field = it }
        f.emptyText.text = "found automatically: the Claude Code plugin's copy, else ~/workspace/human-review"
        val jcef = PageView.get().supported()
        val box = JBCheckBox("Open the review page in the Human Review tool window, beside the code",
            HumanReviewSettings.get().pageInIde).also { inIde = it }
        return FormBuilder.createFormBuilder()
            .addLabeledComponent("serve-review.py:", f)
            .addComponent(box)
            .addComponentToRightColumn(JBLabel(if (jcef) "Off: the status-bar item opens it in the OS browser."
                else "This IDE has no embedded browser (JCEF): the page opens in the OS browser.").apply {
                componentStyle = UIUtil.ComponentStyle.SMALL
                foreground = UIUtil.getContextHelpForeground()
            })
            .addComponentFillVertically(javax.swing.JPanel(), 0)
            .panel
    }

    override fun isModified() = field?.text?.trim() != HumanReviewSettings.get().serveScript ||
        inIde?.isSelected != HumanReviewSettings.get().pageInIde

    override fun apply() {
        HumanReviewSettings.get().serveScript = field?.text ?: ""
        inIde?.let { HumanReviewSettings.get().pageInIde = it.isSelected }
    }

    override fun reset() {
        field?.text = HumanReviewSettings.get().serveScript
        inIde?.isSelected = HumanReviewSettings.get().pageInIde
    }

    override fun disposeUIResources() {
        field = null
        inIde = null
    }
}
