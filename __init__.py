# -*- coding: utf-8 -*-

"""
Nickolay Nonard <kelciour@gmail.com>
"""

import json
import requests
import time
import io
import os
import re
import subprocess
import urllib.parse
import sys
import threading

from bs4 import BeautifulSoup

from aqt.qt import *
from PyQt6.QtNetwork import QNetworkCookie, QNetworkCookieJar

from aqt.utils import showInfo, showText, tooltip
from anki.hooks import addHook
from anki.lang import ngettext
from anki.utils import checksum, tmpfile, no_bundled_libs

from anki.sound import _packagedCmd, si
try:
    from distutils.spawn import find_executable
except:
    from shutil import which as find_executable

try:
    from .designer import form_qt6 as form
except:
    from .designer import form_qt5 as form
# https://github.com/glutanimate/html-cleaner/blob/master/html_cleaner/main.py#L59
sys.path.append(os.path.join(os.path.dirname(__file__), "vendor"))

import concurrent.futures

import warnings
# https://github.com/python-pillow/Pillow/issues/3352#issuecomment-425733696
warnings.filterwarnings("ignore", "(Possibly )?corrupt EXIF data", UserWarning)


headers = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
  "Accept-Encoding": "gzip, deflate, br",
  "Connection": "keep-alive",
  "Cache-Control": "max-age=0",
  "Pragma": "no-cache",
  "Upgrade-Insecure-Requests": "1",
  "Sec-Fetch-Site": "none",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-User": "?1",
  "Sec-Fetch-Dest": "document"
}

rq_user_agent = "Opera/9.80 (iPad; Opera Mini/5.0.17381/503; U; eu) Presto/2.6.35 Version/11.10)"

info = None
if is_win:
    info = subprocess.STARTUPINFO()
    info.wShowWindow = subprocess.SW_HIDE
    info.dwFlags = subprocess.STARTF_USESHOWWINDOW

class GoogleHelper(QDialog):
    def __init__(self, query, browser, hide, mw):
        QDialog.__init__(self, browser)
        self.start = False
        self.finish = False
        self.ready = None
        self.hide = hide
        self.query = query
        self.is_captcha = False
        self.content = ""
        self.results = []
        self.count = 0
        self.mw = mw
        self.startTime = time.time()
        self.initUI()

    def initUI(self):
        self.webEngineView = QWebEngineView(self)
        self.webEnginePage = QWebEnginePage(self.webEngineView)
        self.webEngineView.setPage(self.webEnginePage)

        layout = QVBoxLayout()
        layout.addWidget(self.webEngineView)
        self.setLayout(layout)

        self.webEngineView.page().urlChanged.connect(self.onLoadFinished)

        self.profile = self.webEngineView.page().profile()
        self.profile.setHttpUserAgent(headers["User-Agent"])
        cookie_store = self.profile.cookieStore()
        cookie = QNetworkCookie(b"CONSENT", b"YES+")
        cookie.setDomain(".google.com")
        cookie.setPath("/")
        cookie.setSecure(True)
        cookie_store.setCookie(cookie)

        self.setWindowTitle("Batch Download Pictures From Google Images")

        self.setWindowState
        self.setMinimumSize(1280, 900)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        if self.hide:
            self.setWindowState(Qt.WindowState.WindowMinimized)
            self.setWindowOpacity(0)

        self.show()

        self.webEngineView.load(QUrl(self.query))

    def onLoadFinished(self):
        self.start = True
        self.updateReadyState()

    def onReadyState(self, state):
        if state != "complete":
            QApplication.instance().processEvents()
            return QTimer.singleShot(1000, self.updateReadyState)
        self.webEngineView.page().runJavaScript(
            "if (document.querySelector('#CXQnmb')) document.querySelector('#L2AGLb').click();"
        )
        self.webEngineView.page().toHtml(self.getHTML)

    def updateReadyState(self):
        self.webEngineView.page().runJavaScript(
            "document.readyState", self.onReadyState
        )

    def getHTML(self, html):
        self.content = html
        if 'id="recaptcha"' in self.content:
            self.mw.progress.finish()
            if self.hide:
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
                self.setWindowOpacity(1)
            self.is_captcha = True
            return
        self.results = getImages(self.content)
        self.count += 1
        if not self.results and self.count < 5:
            return QTimer.singleShot(1500, self.updateReadyState)
        self.finish = True
        self.done(0)

def getImages(html):
    soup = BeautifulSoup(html, "html.parser")
    rg_meta = soup.find_all("div", {"class": "rg_meta"})
    metadata = [json.loads(e.text) for e in rg_meta]
    results = [d["ou"] for d in metadata]

    if not results:
        results = re.findall(r'data-ou="([^"]+)"', html)

    if not results:
        texts = []

        regex = re.escape("AF_initDataCallback({")
        regex += r'[^<]*?data:[^<]*?' + r'(\[[^<]+\])'

        for txt in re.findall(regex, html):
            texts.append(txt)

        regex = r'var m=(\{"[^"]+":\[.+?\]\});'

        for txt in re.findall(regex, html):
            texts.append(txt)

        for txt in texts:
            data = json.loads(txt)

            try:
                for d in data[31][0][12][2]:
                    try:
                        results.append(d[1][3][0])
                    except Exception as e:
                        pass
            except Exception as e:
                pass

            try:
                for d in data[56][1][0][0][1][0]:
                    try:
                        d = d[0][0]["444383007"]
                        results.append(d[1][3][0])
                    except:
                        pass
            except:
                pass

            try:
                for key in data:
                    try:
                        for d in data[key]:
                            try:
                                if len(d) == 10 and len(d[3]) == 3:
                                   results.append(d[3][0])
                            except:
                                pass
                    except:
                        pass
            except:
                pass

    return results

def updateNotes(browser, nids):
    try:
        from PIL import Image, ImageSequence, UnidentifiedImageError
        is_PIL = True
    except:
        is_PIL = False

    mw = browser.mw

    d = QDialog(browser)
    frm = form.Ui_Dialog()
    frm.setupUi(d)

    config = mw.addonManager.getConfig(__name__)

    mpv_executable, env = find_executable("mpv"), os.environ
    if mpv_executable is None:
        mpv_path, env = _packagedCmd(["mpv"])
        mpv_executable = mpv_path[0]
        try:
            with no_bundled_libs():
                p = subprocess.Popen([mpv_executable, "--version"], startupinfo=si)
        except OSError:
            mpv_executable = None

    note = mw.col.get_note(nids[0])
    fields = note.keys()

    frm.srcField.addItems(fields)
    fld = config["Source Field"]
    if fld in fields:
        frm.srcField.setCurrentIndex(fields.index(fld))

    for i, sq in enumerate(config["Search Queries"], 1):
        name = sq["Name"]
        url = sq["URL"]
        fld = sq["Field"]
        cnt = sq.get("Count", 1)
        width = sq.get("Width", -1)
        height = sq.get("Height", 260)
        overwrite = sq.get("Overwrite", "Skip")

        # backward compatibility with the previous version
        if overwrite == True:
            overwrite = "Overwrite"
        elif overwrite == False:
            overwrite = "Skip"

        lineEdit = QLineEdit(name)
        frm.gridLayout.addWidget(lineEdit, i, 0)

        lineEdit = QLineEdit(url)
        frm.gridLayout.addWidget(lineEdit, i, 1)

        combobox = QComboBox()
        combobox.setObjectName("targetField")
        combobox.addItem("<ignored>")
        combobox.addItems(fields)
        if fld in fields:
            combobox.setCurrentIndex(fields.index(fld) + 1)
        frm.gridLayout.addWidget(combobox, i, 2)

        spinBox = QSpinBox()
        spinBox.setMinimum(1)
        spinBox.setValue(cnt)
        spinBox.setStyleSheet("""
           QSpinBox {
            width: 24;
        }""")
        frm.gridLayout.addWidget(spinBox, i, 3)

        checkBox = QComboBox()
        checkBox.setObjectName("checkBox")
        checkBox.addItem("Skip")
        checkBox.addItem("Overwrite")
        checkBox.addItem("Append")
        checkBox.setCurrentIndex(checkBox.findText(overwrite))
        frm.gridLayout.addWidget(checkBox, i, 4)

        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Width:"))
        spinBox = QSpinBox()
        spinBox.setMinimum(-1)
        spinBox.setMaximum(9999)
        spinBox.setValue(width)
        spinBox.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(spinBox)
        frm.gridLayout.addLayout(hbox, i, 5)

        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Height:"))
        spinBox = QSpinBox()
        spinBox.setMinimum(-1)
        spinBox.setMaximum(9999)
        spinBox.setValue(height)
        spinBox.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(spinBox)
        frm.gridLayout.addLayout(hbox, i, 6)

    frm.gridLayout.setColumnStretch(1, 1)
    frm.gridLayout.setColumnMinimumWidth(1, 120)

    columns = ["Name:", "Search Query:", "Target Field:", "Count:", "If not empty?", '', '']
    for i, title in enumerate(columns):
        frm.gridLayout.addWidget(QLabel(title), 0, i)

    frm.cbShowWindow.setChecked(not config["Hide Window"])

    frm.cbUseQtBrowser.setChecked(config["Use QtBrowser"])

    if not config["Use QtBrowser"]:
        frm.cbShowWindow.setEnabled(False)
    else:
        frm.cbShowWindow.setEnabled(True)

    def state_changed():
        frm.cbShowWindow.setEnabled(frm.cbUseQtBrowser.isChecked())

    frm.cbUseQtBrowser.stateChanged.connect(state_changed)

    if not d.exec():
        return

    sf = frm.srcField.currentText()

    sq = []
    columns = ["Name", "URL", "Field", "Count", 'Overwrite', 'Width', 'Height']
    for i in range(1, frm.gridLayout.rowCount()):
        q = {}
        for j in range(frm.gridLayout.columnCount()):
            key = columns[j]
            if not key:
                continue
            item = frm.gridLayout.itemAtPosition(i, j)

            if isinstance(item, QWidgetItem):
                item = item.widget()
            elif isinstance(item, QLayoutItem):
                item = item.itemAt(1).widget()

            if isinstance(item, QComboBox) and item.objectName() == "targetField":
                q[key] = item.currentText()
                if q[key] == "<ignored>":
                    q[key] = ""
            elif isinstance(item, QSpinBox):
                q[key] = item.value()
            elif isinstance(item, QComboBox) and item.objectName() == "checkBox":
                q[key] = item.currentText()
            else:
                q[key] = item.text()
        sq.append(q)

    config["Source Field"] = sf
    config["Search Queries"] = sq
    config["Hide Window"] = not frm.cbShowWindow.isChecked()
    config["Use QtBrowser"] = frm.cbUseQtBrowser.isChecked()

    hide_window = config["Hide Window"]

    mw.addonManager.writeConfig(__name__, config)

    def sleep(seconds):
        start = time.time()
        while time.time() - start < seconds:
            time.sleep(0.01)
            QApplication.instance().processEvents()

    def updateField(nid, fld, images, overwrite):
        imgs = []
        for fname, data in images:
            fname = mw.col.media.write_data(fname, data)
            filename = '<img src="%s">' % fname
            imgs.append(filename)
        note = mw.col.get_note(nid)
        delimiter = config.get("Delimiter", " ")
        if overwrite == "Append":
            if imgs and note[fld]:
                note[fld] += delimiter
            note[fld] += delimiter.join(imgs)
        else:
            note[fld] = delimiter.join(imgs)
        mw.col.update_note(note)

    for q in sq:
        if q["Field"]:
            break
    else:
        tooltip("No Target Field selected.")
        return

    error_msg = ""
    error_source_field_not_found = 0
    error_target_field_not_found = 0
    is_consent_error = False
    is_search_error = False
    mw.progress.start(parent=browser)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        jobs = []
        processed = set()
        for c, nid in enumerate(nids, 1):
            if is_search_error:
                break

            note = mw.col.get_note(nid)

            if sf not in note:
                error_source_field_not_found += 1
                continue

            w = note[sf]

            is_search_error = False
            is_target_field_found = False
            for q in sq:
                df = q["Field"]

                if not df:
                    continue

                if df not in note:
                    continue

                is_target_field_found = True

                if note[df] and q["Overwrite"] == "Skip":
                    continue

                def downloadImages(nid, fld, html, img_width, img_height, img_count, fld_overwrite):
                    cnt = 0
                    images = []
                    for url in results:
                        try:
                            r = requests.get(url, headers=headers, timeout=15)
                            QApplication.instance().processEvents()
                            r.raise_for_status()
                            data = r.content
                            if 'text/html' in r.headers.get('content-type', ''):
                                continue
                            if 'image/svg+xml' in r.headers.get('content-type', ''):
                                continue
                            url = re.sub(r"\?.*?$", "", url)
                            path = urllib.parse.unquote(url)
                            fname = os.path.basename(path)
                            if fname.startswith('_'):
                                fname = fname.lstrip('_')
                            if not fname:
                                fname = checksum(data)
                            if img_width > 0 or img_height > 0:
                                if is_PIL:
                                    try:
                                        im = Image.open(io.BytesIO(data))
                                    except UnidentifiedImageError:
                                        continue
                                    width, height = im.width, im.height
                                    if img_width > 0:
                                        width = min(width, img_width)
                                    if img_height > 0:
                                        height = min(height, img_height)
                                    buf = io.BytesIO()
                                    if getattr(im, 'n_frames', 1) == 1:
                                        im.thumbnail((width, height))
                                        im.save(buf, format=im.format, optimize=True)
                                    else:
                                        buf = io.BytesIO(data)
                                    data = buf.getvalue()
                                elif mpv_executable:
                                    thread_id = threading.get_native_id()
                                    tmp_path = tmpfile(suffix='.{}'.format(thread_id))
                                    with open(tmp_path, 'wb') as f:
                                        f.write(data)
                                    img_ext = (os.path.splitext(fname)[-1]).lower()
                                    if img_ext not in ['.jpg', '.jpeg', '.gif', '.png']:
                                        img_ext = '.jpg'
                                    img_path = tmpfile(suffix=img_ext)
                                    cmd = [mpv_executable, tmp_path, "--no-audio", "-frames", "1", "-vf", "lavfi=[scale='min({},iw)':'min({},ih)':force_original_aspect_ratio=decrease:out_range=pc:flags=lanczos]".format(img_width, img_height), "-o", img_path]
                                    with no_bundled_libs():
                                        p = subprocess.Popen(cmd, startupinfo=info)
                                    ret = p.wait()
                                    if ret == 0:
                                        with open(img_path, 'rb') as f:
                                            data = f.read()
                            images.append((fname, data))
                            cnt += 1
                            if cnt == img_count:
                                break
                        except requests.packages.urllib3.exceptions.LocationParseError:
                            pass
                        except requests.exceptions.RequestException:
                            pass
                        except UnicodeError as e:
                            # UnicodeError: encoding with 'idna' codec failed (UnicodeError: label empty or too long)
                            # https://bugs.python.org/issue32958
                            if str(e) != "encoding with 'idna' codec failed (UnicodeError: label empty or too long)":
                                raise
                    return (nid, fld, images, fld_overwrite)

                w = re.sub(r'</?(b|i|u|strong|span)(?: [^>]+)>', '', w)
                w = re.sub(r'\[sound:.*?\]', '', w)
                if '<' in w:
                    soup = BeautifulSoup(w, "html.parser")
                    for s in soup.stripped_strings:
                        w = s
                        break
                    else:
                        w = re.sub(r'<br ?/?>[\s\S]+$', ' ', w)
                        w = re.sub(r'<[^>]+>', '', w)

                clozes = re.findall(r'{{c\d+::(.*?)(?::.*?)?}}', w)
                if clozes:
                    w = ' '.join(clozes)

                query = q["URL"].replace("{}", w)

                query = query.strip()
                if not query:
                    continue

                retry_cnt = 0

                while True:
                    try:
                        payload = {
                            "q": query,
                            "tbm": "isch",
                            "ie": "utf8",
                            "oe": "utf8",
                            "ucbcb": "1",
                            "safe": "active",
                            "udm": "2"
                        }

                        if config["Use QtBrowser"]:
                            ex = GoogleHelper("https://www.google.com/search?" + urllib.parse.urlencode(payload), browser, hide_window, mw)
                            ex.exec()
                            data = ex.content
                            results = ex.results
                        else:
                            payload["tbs"] = "itp:photo,ic:color,iar:w"
                            rq_headers = headers
                            rq_headers["User-Agent"] = rq_user_agent
                            r = requests.get("https://www.google.com/search", params=payload, headers=rq_headers, cookies={"CONSENT":"YES+"}, timeout=15)
                            r.raise_for_status()
                            data = r.text
                            results = getImages(data)
                        QApplication.instance().processEvents()
                        # if '/consent.google.com/' in r.url:
                        #     is_consent_error = True
                        #     break
                        if not results and (len(nids) == 1 or (config["Use QtBrowser"] and ex.is_captcha)):
                            is_search_error = True
                            showText(data, title="[DEBUG] Google Images", copyBtn=True)
                            break
                        if config["Use QtBrowser"] and ex.is_captcha:
                            mw.progress.start()
                        future = executor.submit(downloadImages, nid, df, results, q["Width"], q["Height"], q["Count"], q["Overwrite"])
                        jobs.append(future)
                        break
                    except requests.exceptions.HTTPError as e:
                        if is_search_error:
                            error_msg = str(e)
                            break
                    except requests.exceptions.RequestException as e:
                        if retry_cnt == 3:
                            raise
                        retry_cnt += 1
                        if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 429:
                            mw.progress.update(f"Sleeping for {retry_cnt * 30} seconds...")
                            QApplication.instance().processEvents()
                            sleep(retry_cnt * 30)
                        elif isinstance(e, (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError)):
                            mw.progress.update(f"Sleeping for {retry_cnt * 5} seconds...")
                            QApplication.instance().processEvents()
                            sleep(retry_cnt * 5)
                        else:
                            raise
                if is_consent_error:
                    break
                if is_search_error:
                    break

            if not is_target_field_found:
                error_target_field_not_found += 1

            done, not_done = concurrent.futures.wait(jobs, timeout=0)
            for future in done:
                nid, fld, images, overwrite = future.result()
                updateField(nid, fld, images, overwrite)
                QApplication.instance().processEvents()
                processed.add(nid)
                jobs.remove(future)
            else:
                label = "Processed %s notes..." % len(processed)
                mw.progress.update(label)
                QApplication.instance().processEvents()

        for future in concurrent.futures.as_completed(jobs):
            nid, fld, images, overwrite = future.result()
            updateField(nid, fld, images, overwrite)
            processed.add(nid)
            label = "Processed %s notes..." % len(processed)
            mw.progress.update(label)
            QApplication.instance().processEvents()

    QApplication.instance().processEvents()
    mw.progress.finish()
    mw.reset()
    if is_consent_error:
        showText('ERROR: "Before you continue to Google" pop-up', parent=browser)
    elif error_msg:
        showText(error_msg, title="Batch Download Pictures from Google Images", parent=browser)
    else:
        msg = ngettext("Processed %d note.", "Processed %d notes.", len(nids)) % len(nids)
        if error_source_field_not_found > 0:
            msg2 = ngettext("Skipped %d note", \
                            "Skipped %d notes", error_source_field_not_found) % error_source_field_not_found
            msg += "\n" + msg2 + ", no Source Field found."
        if error_target_field_not_found > 0:
            msg2 = ngettext("Skipped %d note", \
                            "Skipped %d notes", error_target_field_not_found) % error_target_field_not_found
            msg += "\n" + msg2 + ", no Target Field found."
        showInfo(msg, parent=browser)


def onAddImages(browser):
    nids = browser.selectedNotes()
    if not nids:
        tooltip("No cards selected.")
        return
    updateNotes(browser, nids)


def setupMenu(browser):
    menu = browser.form.menuEdit
    menu.addSeparator()
    a = menu.addAction('Add Google Images')
    a.triggered.connect(lambda _, b=browser: onAddImages(b))


addHook("browser.setupMenus", setupMenu)