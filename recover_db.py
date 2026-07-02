"""
Obnova poškozené SQLite databáze a regenerace HTML ze šablony.
"""
import sqlite3, os, shutil, json

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_BROKEN   = os.path.join(SCRIPT_DIR, 'golf_new.db')
DB_FIXED    = os.path.join(SCRIPT_DIR, 'golf_new_fixed.db')
HTML_PATH   = os.path.join(SCRIPT_DIR, 'golf_prototype.html')
INDEX_PATH  = os.path.join(SCRIPT_DIR, 'index.html')
TEMPLATE    = os.path.join(SCRIPT_DIR, 'golf_template.html')

print('=== Obnova databáze ===')

# 1. Pokus o backup přes sqlite3.backup()
if os.path.exists(DB_FIXED):
    os.remove(DB_FIXED)
try:
    src = sqlite3.connect(DB_BROKEN)
    dst = sqlite3.connect(DB_FIXED)
    src.backup(dst)
    dst.close(); src.close()
    print('Záloha přes backup() OK')
except Exception as e:
    print(f'backup() selhal: {e}')
    try:
        conn = sqlite3.connect(DB_BROKEN)
        conn.execute(f"VACUUM INTO '{DB_FIXED}'")
        conn.close()
        print('VACUUM INTO OK')
    except Exception as e2:
        print(f'VACUUM INTO také selhal: {e2}')
        exit(1)

# 2. Ověř počty v opravené DB
conn = sqlite3.connect(DB_FIXED)
try:
    t_count = conn.execute('SELECT COUNT(*) FROM tournaments').fetchone()[0]
    r_count = conn.execute('SELECT COUNT(*) FROM results').fetchone()[0]
    c_count = conn.execute('SELECT COUNT(*) FROM categories').fetchone()[0]
    print(f'Obnoveno: {t_count} turnajů, {c_count} kategorií, {r_count} výsledků')
except Exception as e:
    print(f'Chyba při čtení opravené DB: {e}')
    conn.close(); exit(1)

# 3. Nahraď původní DB opravenou
conn.close()
shutil.copy2(DB_FIXED, DB_BROKEN)
print('golf_new.db nahrazena opravenou verzí')

# 4. Načti data z DB
print('Načítám data pro regeneraci HTML...')
conn = sqlite3.connect(DB_FIXED)

t_rows = conn.execute(
    'SELECT id, name, venue, date_from FROM tournaments ORDER BY date_from DESC'
).fetchall()
tournaments = [{'id': r[0], 'name': r[1], 'venue': r[2], 'date': r[3]} for r in t_rows]
print(f'Turnaje: {len(tournaments)}')

c_rows = conn.execute('SELECT id, tournament_id, name FROM categories').fetchall()
categories = [{'id': r[0], 'tournament_id': r[1], 'name': r[2]} for r in c_rows]
print(f'Kategorie: {len(categories)}')

results = []
skipped = 0
try:
    cursor = conn.execute(
        '''SELECT tournament_id, category_id, position, name, club, member_no,
                  hcp_before, hcp_after, gross, stableford, result_text, golfer_id
           FROM results ORDER BY tournament_id, category_id, position'''
    )
    while True:
        try:
            row = cursor.fetchone()
            if row is None:
                break
            pos = row[2]
            try: pos = int(pos)
            except: pass
            results.append({
                'tournament_id': row[0], 'category_id': row[1], 'pos': pos,
                'name': row[3], 'club': row[4], 'member_no': row[5],
                'hcp_before': row[6], 'hcp_after': row[7],
                'gross': row[8], 'stableford': row[9],
                'result': row[10], 'golfer_id': row[11],
            })
        except Exception as row_err:
            skipped += 1
except Exception as e:
    print(f'Čtení results skončilo: {e}')

print(f'Výsledky: {len(results)} načteno, {skipped} přeskočeno')
conn.close()

# 5. Regeneruj HTML ze šablony
if not os.path.exists(TEMPLATE):
    print(f'CHYBA: Šablona nenalezena: {TEMPLATE}')
    print('Nejprve spusťte: python write_template.py')
    exit(1)

print('Čtu šablonu...')
with open(TEMPLATE, encoding='utf-8') as f:
    template_html = f.read()

if '%%DATA%%' not in template_html:
    print('CHYBA: Šablona neobsahuje placeholder %%DATA%%')
    exit(1)

data_json = json.dumps(
    {'tournaments': tournaments, 'categories': categories, 'results': results},
    ensure_ascii=False, separators=(',', ':')
)
new_html = template_html.replace('%%DATA%%', data_json)

with open(HTML_PATH, 'w', encoding='utf-8') as f:
    f.write(new_html)
    f.flush()
    os.fsync(f.fileno())

shutil.copy2(HTML_PATH, INDEX_PATH)

size = os.path.getsize(HTML_PATH)
# Ověření
with open(HTML_PATH, encoding='utf-8') as f:
    check = f.read()

ok_data      = '"results":[' in check
ok_search    = 'searchInput.addEventListener' in check
ok_render    = 'function render()' in check
ok_dashboard = 'renderDashboard' in check

print(f'Hotovo! Soubor: {size:,} bajtů')
print(f'  DATA.results OK:  {ok_data}')
print(f'  search OK:        {ok_search}')
print(f'  render() OK:      {ok_render}')
print(f'  dashboard OK:     {ok_dashboard}')
print(f'Soubory aktualizovány: golf_prototype.html + index.html')
