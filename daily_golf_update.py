#!/usr/bin/env python3
"""
Golf DB Daily Update Script
============================
Scrapuje cgf.cz pro zadaný datum (výchozí: včerejšek), ukládá výsledky
do SQLite databáze a regeneruje golf_prototype.html.

Použití:
    python daily_golf_update.py              # včerejšek
    python daily_golf_update.py 2026-06-18   # konkrétní datum
    python daily_golf_update.py 2026-06-01 2026-06-15  # rozsah
"""

import sqlite3
import re
import time
import sys
import json
import os
import urllib.request
import urllib.error
from datetime import date, timedelta, datetime

# ── Cesty ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, 'golf_new.db')
HTML_PATH = os.path.join(SCRIPT_DIR, 'golf_prototype.html')
LOG_PATH = os.path.join(SCRIPT_DIR, 'daily_update.log')

BASE_URL = 'https://www.cgf.cz'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'cs-CZ,cs;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}
REQUEST_DELAY = 0.8   # sekundy mezi requesty
TIMEOUT = 20          # timeout pro každý request


# ── Logging ────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ── HTTP ───────────────────────────────────────────────────────────────────
def fetch(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code} pro {url}')
    except Exception as e:
        raise RuntimeError(f'Fetch error {url}: {e}')


# ── HTML helpers ────────────────────────────────────────────────────────────
def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip()


def parse_date_cz(s):
    """'05. 06. 2026' → '2026-06-05'"""
    m = re.search(r'(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})', s)
    if m:
        return f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    return None


def parse_hcp(s):
    """Převede HCP string na float. '+0,9' → -0.9, '27,6' → 27.6, 'PRO' → None"""
    s = s.strip()
    if not s or s in ('PRO', '-', ''):
        return None
    s = s.replace(',', '.')
    try:
        if s.startswith('+'):
            return -float(s[1:])
        return float(s)
    except ValueError:
        return None


# ── Scraping ────────────────────────────────────────────────────────────────
def get_tournament_ids_for_date(d):
    """Vrátí seznam ID turnajů ukončených v daný den."""
    ds = d.strftime('%Y-%m-%d')
    url = f'{BASE_URL}/cz/turnaje/turnaje-vyhledavani?dateFrom={ds}&dateTo={ds}&state=finished'
    html = fetch(url)
    ids = list(set(re.findall(r'turnaje-vyhledavani/turnaj\?id=(\d+)', html)))
    return ids


def get_tournament_ids_for_range(date_from, date_to):
    """Vrátí seznam ID turnajů pro celý rozsah datumů najednou (spolehlivější)."""
    df = date_from.strftime('%Y-%m-%d')
    dt = date_to.strftime('%Y-%m-%d')
    url = f'{BASE_URL}/cz/turnaje/turnaje-vyhledavani?dateFrom={df}&dateTo={dt}&state=finished'
    html = fetch(url)
    ids = list(set(re.findall(r'turnaje-vyhledavani/turnaj\?id=(\d+)', html)))
    return ids


def get_tournament_info(tid):
    """Vrátí info o turnaji: name, venue, date, days, rounds, category IDs."""
    # Nejprve detail stránka pro název, datum, hřiště
    url_detail = f'{BASE_URL}/cz/turnaje/turnaje-vyhledavani/turnaj?id={tid}'
    html_detail = fetch(url_detail)

    # Název turnaje
    name_m = re.search(r'<h1[^>]*class="[^"]*heading[^"]*"[^>]*>(.*?)</h1>', html_detail, re.DOTALL)
    if not name_m:
        name_m = re.search(r'<h1[^>]*>(.*?)</h1>', html_detail, re.DOTALL)
    name = strip_tags(name_m.group(1)) if name_m else f'Turnaj {tid}'

    # Datum
    date_str = parse_date_cz(html_detail)

    # Hřiště — hledáme typické vzory v DT tabulce
    venue = ''
    vm = re.search(r'(?:Hřiště|Golf\s*Club|Venue)[^:]*:[^<]*<[^>]*>([^<]{3,60})<', html_detail)
    if vm:
        venue = vm.group(1).strip()
    if not venue:
        vm2 = re.search(r'</h1>\s*<[^>]+>\s*([^<]{5,60}Golf[^<]{0,40})<', html_detail, re.IGNORECASE)
        if vm2:
            venue = vm2.group(1).strip()

    # Kategorie — nový formát: vysledkova-listina?id=TID obsahuje categoryId v odkazech
    time.sleep(REQUEST_DELAY)
    url_listina = f'{BASE_URL}/cz/turnaje/turnaje-vyhledavani/turnaj/vysledkova-listina?id={tid}'
    html_listina = fetch(url_listina)
    # Vzor: vysledkova-listina-kategorie?id=1300147101&categoryId=362641
    cat_ids = list(set(re.findall(
        r'vysledkova-listina-kategorie\?id=\d+&(?:amp;)?categoryId=(\d+)', html_listina
    )))

    return {
        'id': tid,
        'name': name,
        'venue': venue,
        'date': date_str,
        'days': 1,
        'rounds': 1,
        'cat_ids': cat_ids,
    }


def get_category_info_and_results(tid, cat_id):
    """Scrapuje výsledkovou listinu kategorie. Vrátí (cat_name, tid_from_page, rows)."""
    # Nový URL formát: id=TOURNAMENT_ID&categoryId=CATEGORY_ID
    url = f'{BASE_URL}/cz/turnaje/turnaje-vyhledavani/turnaj/vysledkova-listina-kategorie?id={tid}&categoryId={cat_id}'
    html = fetch(url)

    # Název kategorie — z nadpisu nebo z caption tabulky
    cat_m = re.search(r'<caption[^>]*>.*?<a[^>]*>([^<]+)</a>', html, re.DOTALL)
    if not cat_m:
        cat_m = re.search(r'<h[23][^>]*>(.*?)</h[23]>', html, re.DOTALL)
    cat_name = strip_tags(cat_m.group(1)) if cat_m else f'Kategorie {cat_id}'

    tid_from_page = tid

    # Parsuj tabulku výsledků
    rows = []
    table_m = re.search(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not table_m:
        return cat_name, tid_from_page, rows

    table_html = table_m.group(1)
    row_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)

    for row_html in row_matches:
        cell_matches = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
        if len(cell_matches) < 6:
            continue

        cells = [strip_tags(c) for c in cell_matches]
        n = len(cells)

        pos = cells[0]
        name = cells[1]
        club = cells[2]
        member_no = cells[3]
        hcp_before_raw = cells[4]
        hcp_after_raw = cells[n - 1]
        score_cols = cells[5:n - 1]

        # Parsuj skóre
        gross = None
        stableford = None
        result_text = None

        if len(score_cols) == 1:
            sc = score_cols[0]
            if '/' in sc:
                parts = sc.split('/')
                g = parts[0].strip()
                s = parts[1].strip()
                try:
                    gross = int(g)
                except ValueError:
                    pass
                try:
                    stableford = int(s)
                except ValueError:
                    pass
                result_text = sc
            else:
                result_text = sc  # WD, NS, DQ, ...
        else:
            # Více kol: "74 / 39", "69 / 44", ..., "213"
            result_text = ' | '.join(score_cols)
            # Stableford z posledního skóre kola (předposlední sloupec)
            last_round = score_cols[-2] if len(score_cols) >= 2 else ''
            if '/' in last_round:
                try:
                    stableford = int(last_round.split('/')[1].strip())
                except ValueError:
                    pass

        hcp_before = parse_hcp(hcp_before_raw)
        hcp_after = parse_hcp(hcp_after_raw)

        # Golfer ID = registrační číslo (member_no)
        golfer_id = member_no if member_no and re.match(r'\d{8,}', member_no) else None

        rows.append({
            'pos': pos,
            'name': name,
            'club': club,
            'member_no': member_no,
            'hcp_before': hcp_before,
            'hcp_after': hcp_after,
            'gross': gross,
            'stableford': stableford,
            'result_text': result_text,
            'golfer_id': golfer_id,
        })

    return cat_name, tid_from_page, rows


# ── Databáze ────────────────────────────────────────────────────────────────
def ensure_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS tournaments (
            id TEXT PRIMARY KEY,
            name TEXT,
            venue TEXT,
            date_from TEXT,
            days INTEGER DEFAULT 1,
            rounds INTEGER DEFAULT 1,
            locked INTEGER DEFAULT 0,
            scraped_at TEXT
        );
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            tournament_id TEXT,
            name TEXT,
            FOREIGN KEY(tournament_id) REFERENCES tournaments(id)
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id TEXT,
            category_id TEXT,
            golfer_id TEXT,
            position TEXT,
            name TEXT,
            club TEXT,
            member_no TEXT,
            hcp_before REAL,
            hcp_after REAL,
            gross INTEGER,
            stableford INTEGER,
            result_text TEXT,
            UNIQUE(tournament_id, category_id, member_no)
        );
    ''')
    conn.commit()


def save_tournament(conn, t, scraped_at):
    conn.execute(
        '''INSERT OR REPLACE INTO tournaments (id, name, venue, date_from, days, rounds, locked, scraped_at)
           VALUES (?,?,?,?,?,?,0,?)''',
        (t['id'], t['name'], t['venue'], t['date'], t['days'], t['rounds'], scraped_at)
    )


def save_category(conn, cat_id, tid, cat_name):
    conn.execute(
        'INSERT OR IGNORE INTO categories (id, tournament_id, name) VALUES (?,?,?)',
        (cat_id, tid, cat_name)
    )


def save_results(conn, tid, cat_id, rows):
    inserted = 0
    for r in rows:
        try:
            conn.execute(
                '''INSERT OR IGNORE INTO results
                   (tournament_id, category_id, golfer_id, position, name, club, member_no,
                    hcp_before, hcp_after, gross, stableford, result_text)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (tid, cat_id, r['golfer_id'], r['pos'], r['name'], r['club'], r['member_no'],
                 r['hcp_before'], r['hcp_after'], r['gross'], r['stableford'], r['result_text'])
            )
            inserted += conn.execute('SELECT changes()').fetchone()[0]
        except Exception as e:
            log(f'  Chyba při vkládání řádku {r["name"]}: {e}')
    return inserted


# ── Regenerace prototypu ────────────────────────────────────────────────────
def export_json_from_db(conn):
    t_rows = conn.execute(
        'SELECT id, name, venue, date_from FROM tournaments ORDER BY date_from DESC'
    ).fetchall()
    tournaments = [
        {'id': r[0], 'name': r[1], 'venue': r[2], 'date': r[3]}
        for r in t_rows
    ]

    c_rows = conn.execute(
        'SELECT id, tournament_id, name FROM categories'
    ).fetchall()
    categories = [
        {'id': r[0], 'tournament_id': r[1], 'name': r[2]}
        for r in c_rows
    ]

    r_rows = conn.execute(
        '''SELECT tournament_id, category_id, position, name, club, member_no,
                  hcp_before, hcp_after, gross, stableford, result_text, golfer_id
           FROM results ORDER BY tournament_id, category_id, position'''
    ).fetchall()
    results = []
    for r in r_rows:
        pos = r[2]
        try: pos = int(pos)
        except: pass
        results.append({
            'tournament_id': r[0],
            'category_id': r[1],
            'pos': pos,
            'name': r[3],
            'club': r[4],
            'member_no': r[5],
            'hcp_before': r[6],
            'hcp_after': r[7],
            'gross': r[8],
            'stableford': r[9],
            'result': r[10],
            'golfer_id': r[11],
        })

    return tournaments, categories, results


def regenerate_prototype(conn):
    import shutil
    template_path = os.path.join(SCRIPT_DIR, 'golf_template.html')
    if not os.path.exists(template_path):
        log(f'Šablona nenalezena: {template_path}')
        log('Spusťte nejprve: python write_template.py')
        return False

    template_html = open(template_path, encoding='utf-8').read()
    if '%%DATA%%' not in template_html:
        log('Šablona neobsahuje %%DATA%% placeholder!')
        return False

    tournaments, categories, results = export_json_from_db(conn)
    data_json = json.dumps(
        {'tournaments': tournaments, 'categories': categories, 'results': results},
        ensure_ascii=False, separators=(',', ':')
    )
    new_html = template_html.replace('%%DATA%%', data_json)

    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_html)
        f.flush()
        os.fsync(f.fileno())

    log(f'Prototyp regenerován: {len(tournaments)} turnajů, {len(results)} výsledků')

    # Synchronizuj index.html = golf_prototype.html (pro GitHub Pages)
    index_path = os.path.join(SCRIPT_DIR, 'index.html')
    try:
        shutil.copy2(HTML_PATH, index_path)
        log('index.html aktualizován')
    except Exception as e:
        log(f'Varování: nepodařilo se zkopírovat index.html: {e}')

    return True


# ── Hlavní logika ───────────────────────────────────────────────────────────
def scrape_date_range(date_from, date_to):
    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)
    scraped_at = datetime.now().isoformat()
    total_new = 0

    # Hledej celý rozsah najednou (cgf.cz nevrací výsledky pro 1-denní rozsahy spolehlivě)
    log(f'Hledám turnaje pro rozsah {date_from} – {date_to}...')
    try:
        tids = get_tournament_ids_for_range(date_from, date_to)
    except Exception as e:
        log(f'Chyba při hledání turnajů: {e}')
        conn.close()
        return 0

    log(f'Nalezeno {len(tids)} turnajů')

    for tid in tids:
        # Přeskoč pokud turnaj už máme a je zamčený
        existing = conn.execute(
            'SELECT locked FROM tournaments WHERE id = ?', (tid,)
        ).fetchone()
        if existing and existing[0]:
            log(f'  {tid}: přeskočen (zamčeno)')
            continue

        try:
            time.sleep(REQUEST_DELAY)
            t_info = get_tournament_info(tid)

            # Filtruj podle data (datum turnaje musí být v zadaném rozsahu)
            if t_info['date']:
                from datetime import date as date_type
                try:
                    t_date = datetime.strptime(t_info['date'], '%Y-%m-%d').date()
                    if not (date_from <= t_date <= date_to):
                        log(f'  {t_info["name"]}: mimo rozsah ({t_info["date"]}), přeskakuji')
                        continue
                except ValueError:
                    pass

            log(f'  Turnaj: {t_info["name"]} [{t_info["date"]}] ({len(t_info["cat_ids"])} kategorií)')
            save_tournament(conn, t_info, scraped_at)
            conn.commit()
        except Exception as e:
            log(f'  Chyba info turnaje {tid}: {e}')
            continue

        for cat_id in t_info['cat_ids']:
            try:
                time.sleep(REQUEST_DELAY)
                cat_name, _, rows = get_category_info_and_results(tid, cat_id)
                save_category(conn, cat_id, tid, cat_name)
                n = save_results(conn, tid, cat_id, rows)
                conn.commit()
                log(f'    Kategorie {cat_name}: {len(rows)} řádků ({n} nových)')
                total_new += n
            except Exception as e:
                log(f'    Chyba kategorie {cat_id}: {e}')

    log(f'Celkem nových výsledků: {total_new}')

    if total_new > 0:
        log('Regeneruji prototyp...')
        regenerate_prototype(conn)

    conn.close()
    return total_new


def main():
    args = sys.argv[1:]

    if len(args) == 0:
        # Výchozí: včerejšek
        d = date.today() - timedelta(days=1)
        date_from = date_to = d
    elif len(args) == 1:
        date_from = date_to = datetime.strptime(args[0], '%Y-%m-%d').date()
    elif len(args) == 2:
        date_from = datetime.strptime(args[0], '%Y-%m-%d').date()
        date_to = datetime.strptime(args[1], '%Y-%m-%d').date()
    else:
        print('Použití: python daily_golf_update.py [YYYY-MM-DD] [YYYY-MM-DD]')
        sys.exit(1)

    log(f'Golf DB Update — rozsah: {date_from} až {date_to}')
    log(f'DB: {DB_PATH}')
    n = scrape_date_range(date_from, date_to)
    log(f'Hotovo. Celkem {n} nových výsledků.')

    # Automatický deploy na GitHub (pokud je git nastavený)
    if n > 0:
        import subprocess
        deploy_bat = os.path.join(SCRIPT_DIR, 'deploy.bat')
        if os.path.exists(deploy_bat):
            log('Spouštím deploy na GitHub...')
            try:
                subprocess.run([deploy_bat], cwd=SCRIPT_DIR, timeout=60)
            except Exception as e:
                log(f'Deploy selhal (nevadí, data jsou v DB): {e}')


if __name__ == '__main__':
    main()
