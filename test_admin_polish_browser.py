"""Check scrolling, section navigation and preservation of editable controls in Edge."""
import unittest
from pathlib import Path
import subprocess
import tempfile

EDGE = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')


class BrowserChecks:
    def browser(self, markup, assertions, width):
        static = (Path(__file__).resolve().parent / 'static').as_uri() + '/'
        markup = markup.decode().replace('src="/static/', 'src="' + static).replace('href="/static/', 'href="' + static)
        probe = """<p id="browser-result">PENDING</p><script>
        window.addEventListener('DOMContentLoaded', () => {
          const assert = (condition, message) => { if (!condition) throw new Error(message); };
          const change = element => element.dispatchEvent(new Event('change', {bubbles:true}));
          try { %s document.getElementById('browser-result').textContent = 'PASS'; }
          catch (error) { document.getElementById('browser-result').textContent = 'FAIL: ' + error.message; }
        });</script>""" % assertions
        with tempfile.TemporaryDirectory(prefix='cl-admin-polish-') as directory:
            page = Path(directory) / 'page.html'
            page.write_text(markup.replace('</body>', probe + '</body>'), encoding='utf-8')
            result = subprocess.run([str(EDGE), '--headless', '--disable-gpu', '--no-sandbox', '--disable-software-rasterizer', '--no-first-run',
                '--window-size=' + str(width) + ',900', '--allow-file-access-from-files',
                '--user-data-dir=' + str(Path(directory) / 'profile'), '--dump-dom',
                '--virtual-time-budget=1500', page.as_uri()], capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=40)
            self.assertIn('<p id="browser-result">PASS</p>', result.stdout, result.stdout[-1800:] + result.stderr[-500:])


@unittest.skipUnless(EDGE.is_file(), 'Microsoft Edge is not installed')
class AdminPolishBrowserTest(unittest.TestCase):
    def test_workspace_controls_at_desktop_and_phone_widths(self):
        rows = ''.join('<tr><td>Record %s</td><td>Details</td></tr>' % i for i in range(80))
        markup = ('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
        <link rel="stylesheet" href="/static/styles.css">
        <link rel="stylesheet" href="/static/admin-workspace.css">
        <link rel="stylesheet" href="/static/admin-polish.css"></head><body>
        <div class="admin"><aside>Tools</aside><main><header><h1>Management</h1></header>
        <section class="panel"><h2>Records</h2><table><thead><tr><th>Name</th><th>Details</th></tr></thead><tbody>'''
        + rows + '''</tbody></table></section>
        <section class="panel"><h2>Notes</h2><form><textarea name="notes">Saved notes</textarea><button>Save</button></form></section>
        <details class="panel settings-fold"><summary>Settings</summary><div class="settings-fold-body"><h2>Business details</h2><input name="business" value="CL Paints"></div></details>
        <section class="panel"><h2>History</h2><p>All records retained.</p></section></main></div>
        <script src="/static/admin-polish.js" defer></script></body></html>''').encode()
        for width in (1280, 390):
            with self.subTest(width=width):
                BrowserChecks.browser(self, markup, '''
                    const area = document.querySelector('.admin-table-scroll');
                    assert(area.scrollHeight > area.clientHeight, 'long table does not scroll');
                    area.scrollTop = 200;
                    assert(area.scrollTop > 0, 'table cannot be scrolled');
                    assert(area.tabIndex === 0 && area.getAttribute('aria-label'), 'scroll area is not keyboard accessible');
                    assert(document.querySelectorAll('tbody tr').length === 80, 'records lost');
                    const menu = document.querySelector('.admin-section-menu select');
                    menu.selectedIndex = 3; change(menu);
                    assert(document.querySelector('details').open, 'section navigation failed to reveal settings');
                    assert(document.querySelector('input[name=business]').value === 'CL Paints', 'settings value changed');
                    assert(document.querySelector('textarea').form.querySelector('button'), 'form controls lost');
                    assert(document.documentElement.scrollWidth <= innerWidth, 'workspace overflows viewport');
                ''', width=width)


if __name__ == '__main__':
    unittest.main()

