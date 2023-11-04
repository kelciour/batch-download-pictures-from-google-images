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
from aqt.utils import showInfo, showText, tooltip
from anki.hooks import addHook
from anki.lang import ngettext
from anki.utils import checksum, tmpfile, noBundledLibs

from anki.sound import _packagedCmd, si
from distutils.spawn import find_executable

from .designer.main import Ui_Dialog

# https://github.com/glutanimate/html-cleaner/blob/master/html_cleaner/main.py#L59
sys.path.append(os.path.join(os.path.dirname(__file__), "vendor"))

import concurrent.futures

import warnings
# https://github.com/python-pillow/Pillow/issues/3352#issuecomment-425733696
warnings.filterwarnings("ignore", "(Possibly )?corrupt EXIF data", UserWarning)


headers = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

info = None
if is_win:
    info = subprocess.STARTUPINFO()
    info.wShowWindow = subprocess.SW_HIDE
    info.dwFlags = subprocess.STARTF_USESHOWWINDOW

def updateNotes(browser, nids):
    try:
        from PIL import Image, ImageSequence, UnidentifiedImageError
        is_PIL = True
    except:
        is_PIL = False

    mw = browser.mw

    d = QDialog(browser)
    frm = Ui_Dialog()
    frm.setupUi(d)

    config = mw.addonManager.getConfig(__name__)

    mpv_executable, env = find_executable("mpv"), os.environ
    if mpv_executable is None:
        mpv_path, env = _packagedCmd(["mpv"])
        mpv_executable = mpv_path[0]
        try:
            with noBundledLibs():
                p = subprocess.Popen([mpv_executable, "--version"], startupinfo=si)
        except OSError:
            mpv_executable = None

    note = mw.col.getNote(nids[0])
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
    mw.addonManager.writeConfig(__name__, config)

    def sleep(seconds):
        start = time.time()
        while time.time() - start < seconds:
            time.sleep(0.01)
            QApplication.instance().processEvents()

    def updateField(nid, fld, images, overwrite):
        if not images:
            return
        imgs = []
        for fname, data in images:
            fname = mw.col.media.writeData(fname, data)
            filename = '<img src="%s">' % fname
            imgs.append(filename)
        note = mw.col.getNote(nid)
        delimiter = config.get("Delimiter", " ")
        if overwrite == "Append":
            if note[fld]:
                note[fld] += delimiter
            note[fld] += delimiter.join(imgs)
        else:
            note[fld] = delimiter.join(imgs)
        note.flush()

    is_consent_error = False
    mw.checkpoint("Add Google Images")
    mw.progress.start(immediate=True)
    browser.model.beginReset()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        jobs = []
        processed = set()
        for c, nid in enumerate(nids, 1):
            note = mw.col.getNote(nid)

            if sf not in note:
                continue

            w = note[sf]

            for q in sq:
                df = q["Field"]

                if not df:
                    continue

                if df not in note:
                    continue

                if note[df] and q["Overwrite"] == "Skip":
                    continue

                def getImages(nid, fld, html, img_width, img_height, img_count, fld_overwrite):
                    soup = BeautifulSoup(html, "html.parser")
                    rg_meta = soup.find_all("div", {"class": "rg_meta"})
                    metadata = [json.loads(e.text) for e in rg_meta]
                    results = [d["ou"] for d in metadata]

                    if not results:
                        regex = re.escape("AF_initDataCallback({")
                        regex += r'[^<]*?data:[^<]*?' + r'(\[[^<]+\])'

                        for txt in re.findall(regex, html):
                            data = json.loads(txt)

                            try:
                                for d in data[31][0][12][2]:
                                    try:
                                        results.append(d[1][3][0])
                                    except Exception as e:
                                        pass
                            except Exception as e:
                                pass

                        if not results:
                            try:
                                for d in data[56][1][0][0][1][0]:
                                    try:
                                        d = d[0][0]["444383007"]
                                        results.append(d[1][3][0])
                                    except:
                                        pass
                            except:
                                pass

                    cnt = 0
                    images = []
                    for url in results:
                        try:
                            r = requests.get(url, headers=headers, timeout=15)
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
                                    with noBundledLibs():
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

                retry_cnt = 0

                while True:
                    try:
                        r = requests.get("https://www.google.com/search?tbm=isch&q={}&safe=active&ie=utf8&oe=utf8&ucbcb=1".format(query), headers=headers, cookies={"CONSENT":"YES+"}, timeout=15)
                        r.raise_for_status()
                        if '/consent.google.com/' in r.url:
                            is_consent_error = True
                            break
                        future = executor.submit(getImages, nid, df, r.text, q["Width"], q["Height"], q["Count"], q["Overwrite"])
                        jobs.append(future)
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

            done, not_done = concurrent.futures.wait(jobs, timeout=0)
            for future in done:
                nid, fld, images, overwrite = future.result()
                updateField(nid, fld, images, overwrite)
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
    browser.model.endReset()
    mw.reset()
    if is_consent_error:
        showText('ERROR: "Before you continue to Google" pop-up', parent=browser)
    else:
        showInfo(ngettext("Processed %d note.", "Processed %d notes.", len(nids)) % len(nids), parent=browser)


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