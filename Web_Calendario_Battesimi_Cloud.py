import os
import re
import json
import sqlite3
import tempfile
import urllib.request
from functools import wraps
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "parrocchia-madonna-rosario-gricignano-2026")

# ==============================================================================
# CONFIGURAZIONE ACCESSO WEB E GOOGLE DRIVE
# ==============================================================================
# Password per consultare il calendario dal web (modificabile o via variabile d'ambiente)
ACCESS_PASSWORD = os.environ.get("CALENDARIO_PASSWORD", "rosario2026")

# ID del file battesimi_parrocchia.db su Google Drive (condiviso con "Chiunque abbia il link -> Visualizzatore")
# Esempio link Drive: https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/view?usp=sharing
# L'ID è la parte tra /d/ e /view
GDRIVE_FILE_ID = os.environ.get("GDRIVE_FILE_ID", "").strip()

CANDIDATE_DB_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "battesimi_parrocchia.db"),
    r"\\DESKTOP-TKPVO0N\Users\HP Win10\Documents\APPLICATIVI_PARROCCHIALI\battesimi_parrocchia.db",
    r"C:\Users\HP Win10\Documents\APPLICATIVI_PARROCCHIALI\battesimi_parrocchia.db",
    r"C:\Users\HPWin10\Documents\APPLICATIVI_PARROCCHIALI\battesimi_parrocchia.db",
    os.path.join(os.path.expanduser("~"), "Documents", "APPLICATIVI_PARROCCHIALI", "battesimi_parrocchia.db"),
    r"G:\Il mio Drive\APPLICATIVI_PARROCCHIALI\battesimi_parrocchia.db",
    r"G:\My Drive\APPLICATIVI_PARROCCHIALI\battesimi_parrocchia.db",
    os.path.join(os.path.expanduser("~"), "Google Drive", "APPLICATIVI_PARROCCHIALI", "battesimi_parrocchia.db"),
]

CACHE_DB_PATH = os.path.join(tempfile.gettempdir(), "battesimi_parrocchia_cloud_cache.db")


def scarica_db_da_gdrive(file_id):
    """Scarica l'ultima versione di battesimi_parrocchia.db da Google Drive."""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
        # Verifica che sia un vero file SQLite (intestazione "SQLite format 3")
        if not data.startswith(b"SQLite format 3"):
            raise RuntimeError("Il file scaricato da Google Drive non è un database SQLite valido. Verifica che il file su Drive sia condiviso come 'Chiunque abbia il link'.")
        with open(CACHE_DB_PATH, "wb") as f:
            f.write(data)
    return CACHE_DB_PATH


def ottieni_percorso_db():
    # 1. Se configurato l'ID Google Drive (modalità Cloud Web), scarica la copia aggiornata
    if GDRIVE_FILE_ID:
        try:
            path = scarica_db_da_gdrive(GDRIVE_FILE_ID)
            return path, "Google Drive Cloud (Sincronizzato online)", None
        except Exception as e:
            if os.path.exists(CACHE_DB_PATH):
                return CACHE_DB_PATH, "Cache locale (Avviso Drive)", str(e)
            return None, "Google Drive", str(e)

    # 2. Altrimenti cerca in locale / rete / Google Drive Desktop
    env_db = os.environ.get("BATTESIMI_DB_PATH")
    if env_db and os.path.exists(env_db):
        return env_db, env_db, None

    for path in CANDIDATE_DB_PATHS:
        if os.path.exists(path):
            return path, path, None

    return None, "Non configurato", "Database battesimi_parrocchia.db non trovato. Imposta GDRIVE_FILE_ID oppure posiziona il file accanto allo script."


def normalizza_data_input(data_str):
    if not data_str:
        return ""
    s = str(data_str).strip()
    parts = re.split(r"[/\-.]", s)
    if len(parts) == 3:
        if len(parts[0]) == 4:
            return f"{parts[2].zfill(2)}/{parts[1].zfill(2)}/{parts[0]}"
        elif len(parts[2]) == 4:
            return f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"
        elif len(parts[2]) == 2:
            return f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/20{parts[2]}"
    return s


def parse_data_ordinamento(data_str):
    s = normalizza_data_input(data_str)
    if "/" in s:
        p = s.split("/")
        if len(p) == 3:
            return f"{p[2].zfill(4)}-{p[1].zfill(2)}-{p[0].zfill(2)}"
    return "9999-99-99"


def carica_battesimi():
    db_path, sorgente, errore = ottieni_percorso_db()
    if not db_path or not os.path.exists(db_path):
        return [], sorgente, errore or "Database non trovato."

    try:
        uri = f"file:{os.path.abspath(db_path)}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM battesimi").fetchall()]
        conn.close()
    except Exception:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute("SELECT * FROM battesimi").fetchall()]
            conn.close()
        except Exception as e:
            return [], sorgente, f"Errore lettura database: {e}"

    risultati = []
    for r in rows:
        data_norm = normalizza_data_input(r.get("data_battesimo", ""))
        iso_date = parse_data_ordinamento(data_norm)
        r["data_battesimo_norm"] = data_norm
        r["iso_date"] = iso_date if re.match(r"^\d{4}-\d{2}-\d{2}$", iso_date) else ""
        r["bimbo_nascita_norm"] = normalizza_data_input(r.get("bimbo_data_nascita", ""))
        r["padre_nascita_norm"] = normalizza_data_input(r.get("padre_data_nascita", ""))
        r["madre_nascita_norm"] = normalizza_data_input(r.get("madre_data_nascita", ""))
        r["padrino_nascita_norm"] = normalizza_data_input(r.get("padrino_data_nascita", ""))
        r["matrimonio_data_norm"] = normalizza_data_input(r.get("matrimonio_data_anno", ""))
        risultati.append(r)

    risultati.sort(key=lambda x: (x["iso_date"] or "9999-99-99", x.get("ora_battesimo") or ""))
    return risultati, sorgente, errore


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ACCESS_PASSWORD:
            return f(*args, **kwargs)
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Accesso Calendario Battesimi</title>
    <style>
        body {
            background: #F5F5F7;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
        }
        .login-card {
            background: white;
            border-radius: 20px;
            padding: 36px 30px;
            max-width: 390px;
            width: 100%;
            box-shadow: 0 12px 35px rgba(0,0,0,0.07);
            text-align: center;
        }
        h2 { margin: 10px 0 6px; color: #1D1D1F; font-size: 1.35rem; }
        p { color: #6E6E73; font-size: 0.9rem; margin-bottom: 22px; }
        input {
            width: 100%;
            padding: 12px 14px;
            border: 1px solid #D2D2D7;
            border-radius: 12px;
            font-size: 1rem;
            margin-bottom: 14px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 12px;
            background: #5856D6;
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
        }
        .err { color: #FF3B30; font-size: 0.86rem; margin-bottom: 12px; font-weight: 600; }
    </style>
</head>
<body>
    <form class="login-card" method="POST">
        <div style="font-size: 2.5rem;">🕊️</div>
        <h2>Parrocchia Madonna del Rosario</h2>
        <p>Inserisci la password della Segreteria per consultare il Calendario Battesimi</p>
        {% if error %}<div class="err">{{ error }}</div>{% endif %}
        <input type="password" name="password" placeholder="Password di accesso" required autofocus>
        <button type="submit">Accedi al Calendario</button>
    </form>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Calendario Battesimi — Parrocchia Madonna del Rosario</title>
    <style>
        :root {
            --bg: #F5F5F7;
            --card: #FFFFFF;
            --text: #1D1D1F;
            --muted: #6E6E73;
            --blue: #0071E3;
            --purple: #5856D6;
            --green: #34C759;
            --border: #E5E5EA;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        body { background: var(--bg); color: var(--text); padding-bottom: 40px; }

        header {
            background: rgba(255, 255, 255, 0.92);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            padding: 14px 24px;
            position: sticky;
            top: 0;
            z-index: 100;
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
        }
        .brand h1 { font-size: 1.2rem; font-weight: 700; }
        .brand p { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }

        .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .btn {
            border: none;
            border-radius: 10px;
            padding: 8px 14px;
            font-size: 0.86rem;
            font-weight: 600;
            cursor: pointer;
            background: #E5E5EA;
            color: var(--text);
            text-decoration: none;
        }
        .btn:hover { filter: brightness(0.95); }
        .btn-blue { background: var(--blue); color: white; }

        .container { max-width: 1200px; margin: 20px auto; padding: 0 16px; }

        .status-bar {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 12px 16px;
            margin-bottom: 16px;
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            font-size: 0.84rem;
        }
        .badge-ok { background: #E8F8ED; color: #1E7E34; padding: 4px 10px; border-radius: 20px; font-weight: 600; }
        .badge-err { background: #FDECEA; color: #C62828; padding: 4px 10px; border-radius: 20px; font-weight: 600; }

        .toolbar {
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }
        .month-nav { display: flex; align-items: center; gap: 8px; }
        .month-title { font-size: 1.3rem; font-weight: 700; min-width: 195px; text-align: center; text-transform: capitalize; }

        .search-box {
            padding: 10px 14px;
            border: 1px solid #D2D2D7;
            border-radius: 10px;
            font-size: 0.9rem;
            width: 280px;
            background: white;
        }

        .tabs { display: flex; gap: 6px; }
        .tab.active { background: var(--text); color: white; }

        .calendar-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.03);
        }
        .weekdays {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            background: #FAFAFC;
            border-bottom: 1px solid var(--border);
            text-align: center;
            font-weight: 700;
            font-size: 0.78rem;
            color: var(--muted);
            padding: 10px 0;
        }
        .days-grid { display: grid; grid-template-columns: repeat(7, 1fr); }
        .day-cell {
            min-height: 112px;
            border-right: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
            padding: 7px;
            background: white;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .day-cell:nth-child(7n) { border-right: none; }
        .day-cell.other-month { background: #F9F9FB; color: #AEAEB2; }
        .day-cell.today { background: #F2F6FF; }
        .day-num { font-size: 0.84rem; font-weight: 700; }
        .today .day-num span {
            background: var(--blue);
            color: white;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }

        .event-pill {
            background: #EFEFFE;
            border-left: 3px solid var(--purple);
            color: #2C2A86;
            padding: 5px 7px;
            border-radius: 6px;
            font-size: 0.76rem;
            font-weight: 600;
            cursor: pointer;
            line-height: 1.25;
        }
        .event-pill:hover { background: #E3E2FD; }
        .event-time { font-size: 0.7rem; color: var(--purple); font-weight: 700; display: block; }

        .list-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 14px;
        }
        .baptism-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px;
            cursor: pointer;
        }
        .baptism-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .date-tag { background: #EFEFFE; color: var(--purple); font-weight: 700; font-size: 0.8rem; padding: 4px 10px; border-radius: 8px; }
        .doc-status { font-size: 0.74rem; font-weight: 600; }
        .baptism-name { font-size: 1.08rem; font-weight: 700; margin-bottom: 6px; }
        .baptism-meta { font-size: 0.84rem; color: var(--muted); line-height: 1.45; }

        .modal-backdrop {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.45);
            z-index: 200;
            align-items: center;
            justify-content: center;
            padding: 16px;
        }
        .modal {
            background: white;
            border-radius: 18px;
            max-width: 600px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 22px;
        }
        .modal-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 14px; }
        .modal-section { margin-bottom: 14px; }
        .modal-section h4 { font-size: 0.76rem; text-transform: uppercase; color: var(--purple); margin-bottom: 6px; }
        .modal-row { font-size: 0.9rem; margin-bottom: 4px; }

        @media (max-width: 760px) {
            .day-cell { min-height: 82px; padding: 4px; }
            .search-box { width: 100%; }
        }
    </style>
</head>
<body>

<header>
    <div class="brand">
        <h1>🕊️ Calendario Battesimi — Parrocchia Madonna del Rosario</h1>
        <p>Consultazione Web Sincronizzata • Gricignano di Aversa (CE)</p>
    </div>
    <div class="controls">
        <button class="btn btn-blue" onclick="aggiornaDati()">🔄 Sincronizza Ora</button>
        <button class="btn" onclick="window.print()">🖨️ Stampa</button>
        <a class="btn" href="/logout">Esci</a>
    </div>
</header>

<div class="container">
    <div class="status-bar">
        <div>
            {% if errore %}
                <span class="badge-err">⚠️ {{ errore }}</span>
            {% else %}
                <span class="badge-ok">● Online e Sincronizzato</span>
                <span style="margin-left: 8px; color: var(--muted);">Battesimi registrati: <strong id="totCount">{{ battesimi|length }}</strong></span>
            {% endif %}
        </div>
        <div style="color: var(--muted); font-size: 0.78rem;">
            Sorgente: <code>{{ sorgente }}</code>
        </div>
    </div>

    <div class="toolbar">
        <div class="month-nav" id="monthNav">
            <button class="btn" onclick="cambiaMese(-1)">◀</button>
            <div class="month-title" id="monthTitle"></div>
            <button class="btn" onclick="cambiaMese(1)">▶</button>
            <button class="btn" onclick="vaiOggi()">Oggi</button>
        </div>

        <input type="text" id="searchInput" class="search-box" placeholder="🔍 Cerca bimbo, genitori, padrino, data..." oninput="renderizzaTutto()">

        <div class="tabs">
            <button class="btn tab active" id="tabCal" onclick="impostaVista('calendario')">📅 Calendario</button>
            <button class="btn tab" id="tabList" onclick="impostaVista('elenco')">📋 Elenco</button>
        </div>
    </div>

    <div id="viewCalendario" class="calendar-card">
        <div class="weekdays">
            <div>LUN</div><div>MAR</div><div>MER</div><div>GIO</div><div>VEN</div><div>SAB</div><div>DOM</div>
        </div>
        <div class="days-grid" id="daysGrid"></div>
    </div>

    <div id="viewElenco" class="list-grid" style="display: none;"></div>
</div>

<div class="modal-backdrop" id="modalBackdrop" onclick="chiudiModal()">
    <div class="modal" onclick="event.stopPropagation()">
        <div class="modal-header">
            <h3 id="modalTitle">Dettaglio Battesimo</h3>
            <button class="btn" onclick="chiudiModal()">✕</button>
        </div>
        <div id="modalBody"></div>
    </div>
</div>

<script>
    let BATTESIMI = {{ battesimi_json | safe }};
    let currentDate = new Date();
    let currentView = 'calendario';

    const MESI = [
        "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
    ];

    function impostaVista(vista) {
        currentView = vista;
        document.getElementById('viewCalendario').style.display = vista === 'calendario' ? 'block' : 'none';
        document.getElementById('viewElenco').style.display = vista === 'elenco' ? 'grid' : 'none';
        document.getElementById('monthNav').style.visibility = vista === 'calendario' ? 'visible' : 'hidden';
        document.getElementById('tabCal').classList.toggle('active', vista === 'calendario');
        document.getElementById('tabList').classList.toggle('active', vista === 'elenco');
        renderizzaTutto();
    }

    function cambiaMese(delta) {
        currentDate.setMonth(currentDate.getMonth() + delta);
        renderizzaTutto();
    }

    function vaiOggi() {
        currentDate = new Date();
        renderizzaTutto();
    }

    function filtraDati() {
        const q = document.getElementById('searchInput').value.trim().toLowerCase();
        if (!q) return BATTESIMI;
        return BATTESIMI.filter(b => {
            const testo = [
                b.bimbo_cognome, b.bimbo_nome, b.data_battesimo_norm,
                b.padre_cognome, b.padre_nome, b.madre_cognome, b.madre_nome,
                b.padrino_cognome, b.padrino_nome, b.domicilio_comune, b.note_documenti
            ].join(' ').toLowerCase();
            return testo.includes(q);
        });
    }

    function renderizzaTutto() {
        const filtrati = filtraDati();
        renderCalendario(filtrati);
        renderElenco(filtrati);
    }

    function renderCalendario(dati) {
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth();
        document.getElementById('monthTitle').textContent = `${MESI[month]} ${year}`;

        const grid = document.getElementById('daysGrid');
        grid.innerHTML = '';

        const firstDay = new Date(year, month, 1);
        let startWeekday = firstDay.getDay() - 1;
        if (startWeekday < 0) startWeekday = 6;

        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const prevMonthDays = new Date(year, month, 0).getDate();
        const todayStr = new Date().toISOString().slice(0, 10);
        const totalCells = Math.ceil((startWeekday + daysInMonth) / 7) * 7;

        for (let i = 0; i < totalCells; i++) {
            const cell = document.createElement('div');
            cell.className = 'day-cell';

            let dayNum, cellYear = year, cellMonth = month;
            if (i < startWeekday) {
                dayNum = prevMonthDays - startWeekday + i + 1;
                cell.classList.add('other-month');
                cellMonth = month - 1;
                if (cellMonth < 0) { cellMonth = 11; cellYear--; }
            } else if (i >= startWeekday + daysInMonth) {
                dayNum = i - (startWeekday + daysInMonth) + 1;
                cell.classList.add('other-month');
                cellMonth = month + 1;
                if (cellMonth > 11) { cellMonth = 0; cellYear++; }
            } else {
                dayNum = i - startWeekday + 1;
            }

            const iso = `${cellYear}-${String(cellMonth + 1).padStart(2, '0')}-${String(dayNum).padStart(2, '0')}`;
            if (iso === todayStr) cell.classList.add('today');

            const numHeader = document.createElement('div');
            numHeader.className = 'day-num';
            numHeader.innerHTML = `<span>${dayNum}</span>`;
            cell.appendChild(numHeader);

            const eventiGiorno = dati.filter(b => b.iso_date === iso);
            eventiGiorno.forEach(ev => {
                const pill = document.createElement('div');
                pill.className = 'event-pill';
                const ora = ev.ora_battesimo ? `<span class="event-time">🕒 ${ev.ora_battesimo}</span>` : '';
                pill.innerHTML = `${ora}${(ev.bimbo_cognome || '').toUpperCase()} ${ev.bimbo_nome || ''}`;
                pill.onclick = () => apriDettaglio(ev);
                cell.appendChild(pill);
            });

            grid.appendChild(cell);
        }
    }

    function renderElenco(dati) {
        const container = document.getElementById('viewElenco');
        container.innerHTML = '';

        if (dati.length === 0) {
            container.innerHTML = '<p style="color: var(--muted); grid-column: 1/-1; text-align:center; padding: 30px;">Nessun battesimo trovato.</p>';
            return;
        }

        dati.forEach(b => {
            const card = document.createElement('div');
            card.className = 'baptism-card';
            card.onclick = () => apriDettaglio(b);

            const docNasc = b.doc_nascita ? '✅ Nascita' : '⏳ Nascita';
            const docIdon = b.doc_idoneita ? '✅ Idoneità' : '⏳ Idoneità';

            card.innerHTML = `
                <div class="baptism-card-header">
                    <span class="date-tag">📅 ${b.data_battesimo_norm || '-'} ${b.ora_battesimo ? '• ' + b.ora_battesimo : ''}</span>
                    <span class="doc-status">${docNasc} | ${docIdon}</span>
                </div>
                <div class="baptism-name">${(b.bimbo_cognome || '').toUpperCase()} ${b.bimbo_nome || ''}</div>
                <div class="baptism-meta">
                    <div><strong>Genitori:</strong> ${b.padre_cognome || ''} ${b.padre_nome || ''} / ${b.madre_cognome || ''} ${b.madre_nome || ''}</div>
                    <div><strong>${b.padrino_ruolo || 'Padrino/Madrina'}:</strong> ${(b.padrino_cognome || '')} ${(b.padrino_nome || '') || 'Non indicato'}</div>
                </div>
            `;
            container.appendChild(card);
        });
    }

    function apriDettaglio(b) {
        document.getElementById('modalTitle').textContent = `${(b.bimbo_cognome || '').toUpperCase()} ${b.bimbo_nome || ''}`;
        document.getElementById('modalBody').innerHTML = `
            <div class="modal-section">
                <h4>Celebrazione</h4>
                <div class="modal-row"><strong>Data Battesimo:</strong> ${b.data_battesimo_norm || '-'} ${b.ora_battesimo ? 'ore ' + b.ora_battesimo : ''}</div>
                <div class="modal-row"><strong>Nato/a a:</strong> ${b.bimbo_luogo_nascita || '-'} il ${b.bimbo_nascita_norm || '-'}</div>
            </div>
            <div class="modal-section">
                <h4>Genitori e Domicilio</h4>
                <div class="modal-row"><strong>Padre:</strong> ${(b.padre_cognome || '').toUpperCase()} ${b.padre_nome || ''} — Tel: ${b.padre_telefono || '-'}</div>
                <div class="modal-row"><strong>Madre:</strong> ${(b.madre_cognome || '').toUpperCase()} ${b.madre_nome || ''} — Tel: ${b.madre_telefono || '-'}</div>
                <div class="modal-row"><strong>Domicilio:</strong> ${b.domicilio_via || '-'} (${b.domicilio_comune || '-'})</div>
                <div class="modal-row"><strong>Situazione Matrimoniale:</strong> ${b.stato_matrimoniale || '-'} ${b.matrimonio_luogo ? '(' + b.matrimonio_luogo + ')' : ''}</div>
            </div>
            <div class="modal-section">
                <h4>${b.padrino_ruolo || 'Padrino / Madrina'}</h4>
                <div class="modal-row"><strong>Nominativo:</strong> ${(b.padrino_cognome || '').toUpperCase()} ${b.padrino_nome || 'Non indicato'}</div>
                <div class="modal-row"><strong>Telefono:</strong> ${b.padrino_telefono || '-'} • <strong>Professione:</strong> ${b.padrino_professione || '-'}</div>
            </div>
            <div class="modal-section">
                <h4>Documenti e Note</h4>
                <div class="modal-row"><strong>Certificato di Nascita:</strong> ${b.doc_nascita ? 'Consegnato ✅' : 'Mancante ❌'}</div>
                <div class="modal-row"><strong>Idoneità Padrino/Madrina:</strong> ${b.doc_idoneita ? 'Consegnato ✅' : 'Mancante ❌'}</div>
                <div class="modal-row"><strong>Note:</strong> ${b.note_documenti || 'Nessuna nota'}</div>
            </div>
        `;
        document.getElementById('modalBackdrop').style.display = 'flex';
    }

    function chiudiModal() {
        document.getElementById('modalBackdrop').style.display = 'none';
    }

    async function aggiornaDati() {
        const res = await fetch('/api/battesimi');
        const json = await res.json();
        BATTESIMI = json.battesimi;
        document.getElementById('totCount').textContent = BATTESIMI.length;
        renderizzaTutto();
    }

    renderizzaTutto();
</script>
</body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ACCESS_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "Password errata. Riprova."
    return render_template_string(LOGIN_TEMPLATE, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    battesimi, sorgente, errore = carica_battesimi()
    return render_template_string(
        HTML_TEMPLATE,
        battesimi=battesimi,
        battesimi_json=json.dumps(battesimi, ensure_ascii=False),
        sorgente=sorgente,
        errore=errore
    )


@app.route("/api/battesimi")
@login_required
def api_battesimi():
    battesimi, sorgente, errore = carica_battesimi()
    return jsonify({"battesimi": battesimi, "sorgente": sorgente, "errore": errore})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
