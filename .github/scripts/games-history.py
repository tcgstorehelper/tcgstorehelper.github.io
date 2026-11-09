#!/usr/bin/env python3
"""Historial de precios de mercado de Pokémon y Yu-Gi-Oh! para la pantalla "Historial de precios" de la web.

Fuente: TCGCSV (gratis, https://tcgcsv.com), que copia una vez por día los precios de TCGplayer y guarda un archivo por
día desde el 2024-02-08 (tcgcsv.com/archive/tcgplayer/prices-AAAA-MM-DD.ppmd.7z, ~4 MB). Cada archivo trae, por
categoría (2 Yu-Gi-Oh!, 3 Pokémon) y por edición, el precio de mercado de cada producto y terminación. Qué carta es cada
producto (nombre, número, rareza) sale de tcgcsv.com/tcgplayer/<categoría>/<edición>/products.

  <salida>/pokemon/<edición>.json  {"version":1,"set":"SV03: Obsidian Flames","updated":"2026-11-09",
                                    "cards":{"63":{"name":"Magnemite","Normal":[["2026-08-11",0.06]],
                                                   "Reverse Holofoil":[...]}}}
      <edición> = el nombre sin el código de adelante, solo letras y números ("obsidianflames").
  <salida>/yugioh/<código>.json    {"version":1,"set":"lob","updated":...,"cards":{"en005|ultrarare":
                                    {"legendofblueeyeswhitedragon":{"name":"Dark Magician","Unlimited":[...]}}}}
      <código> = lo de antes del guion del número ("LOB-EN005" -> "lob"). Una misma carta puede estar en varias
      ediciones (reimpresiones con el mismo número): por eso va una entrada por edición.
  <salida>/<juego>-info.json       {"updated","through":"último día leído","files":[...],"codes":{"sv03":"obsidianflames"}}

Cada serie guarda solo los días en que el precio cambió. La primera vez se arma el historial hacia atrás (un día por
semana hasta hace 90 días y todos los días después); de a MAX_DAYS_PER_RUN días por corrida para no tardar horas. Las
corridas siguientes suman solo los días nuevos. Se guardan hasta 2 años.

Uso: python3 games-history.py <carpeta de salida> <carpeta temporal>
"""
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

API = 'https://tcgcsv.com'
FIRST_ARCHIVE = datetime.date(2024, 2, 8)
MAX_DAYS = 730
DAILY_DAYS = 90
MAX_DAYS_PER_RUN = int(os.environ.get('MAX_DAYS_PER_RUN', '60'))
GAMES = {'pokemon': 3, 'yugioh': 2}
USER_AGENT = 'tcgstorehelper-price-history/1.0 (+https://tcgstorehelper.github.io)'


def get(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def get_json(url):
    return json.loads(get(url))


def slug(text):
    """Nombre de edición comparable: sin "SV03: " adelante, sin "Set" al final, solo letras y números."""
    t = re.sub(r'^[A-Za-z0-9.\-]+:\s+', '', str(text or '').strip()).lower()
    t = re.sub(r'[^a-z0-9]', '', t)
    return re.sub(r'set$', '', t) or t


def number_key(number):
    """Pokémon: "063/197" -> "63"."""
    n = str(number or '').split('/')[0].strip().lower()
    return n.lstrip('0') or n


def safe_name(text):
    s = re.sub(r'[^a-z0-9_-]', '', text.lower())
    return f'_{s}' if s in ('con', 'prn', 'aux', 'nul') else s


def extended(product, field):
    for e in product.get('extendedData') or []:
        if e.get('name') == field:
            return str(e.get('value') or '').strip()
    return ''


def read_products(game, category):
    """productId -> (archivo, clave, edición, nombre). También los códigos que llevan a cada archivo de Pokémon."""
    groups = get_json(f'{API}/tcgplayer/{category}/groups')['results']
    products, codes = {}, {}
    for g in groups:
        try:
            items = get_json(f"{API}/tcgplayer/{category}/{g['groupId']}/products")['results']
        except Exception as e:
            print(f"::warning::No se pudieron leer los productos de {g['name']}: {e}")
            continue
        gslug = slug(g['name'])
        if not gslug:
            continue
        if game == 'pokemon':
            prefix = re.match(r'^([A-Za-z0-9.\-]+):\s+', g['name'])
            for code in {(prefix.group(1) if prefix else ''), g.get('abbreviation') or ''}:
                c = code.strip().lower()
                if c:
                    codes.setdefault(c, set()).add(gslug)
        for p in sorted(items, key=lambda p: p['productId']):
            number = extended(p, 'Number')
            if not number:
                continue  # sobres, cajas, etc.
            if game == 'pokemon':
                products[p['productId']] = (gslug, number_key(number), g['name'], p.get('name') or '')
            else:
                code, _, rest = number.partition('-')
                rarity = re.sub(r'[^a-z0-9]', '', extended(p, 'Rarity').lower())
                if not rest:
                    continue
                key = f'{rest.strip().lower()}|{rarity}'
                products[p['productId']] = (safe_name(code), key, gslug, p.get('name') or '')
    # Un código que lleva a dos ediciones distintas no sirve para encontrar la carta.
    unique = {c: next(iter(s)) for c, s in codes.items() if len(s) == 1}
    print(f'{game}: {len(groups)} ediciones, {len(products)} cartas.')
    return products, unique


def schedule(through, latest):
    """Días a leer: uno por semana hasta hace 90 días y después todos, más nuevos que `through`."""
    start = max(FIRST_ARCHIVE, latest - datetime.timedelta(days=MAX_DAYS))
    daily_from = latest - datetime.timedelta(days=DAILY_DAYS)
    days, d = [], start
    while d <= latest:
        if d >= daily_from or (d - start).days % 7 == 0:
            if through is None or d > through:
                days.append(d)
        d += datetime.timedelta(days=1)
    return days


def read_archive(day, tmp):
    """{categoría: {productId: {terminación: precio}}} de un día; None si ese día no está."""
    path = os.path.join(tmp, 'a.7z')
    out = os.path.join(tmp, 'x')
    shutil.rmtree(out, ignore_errors=True)
    try:
        with open(path, 'wb') as f:
            f.write(get(f'{API}/archive/tcgplayer/prices-{day.isoformat()}.ppmd.7z'))
    except Exception as e:
        print(f'::warning::No se pudo bajar el archivo del {day}: {e}')
        return None
    subprocess.run(['7z', 'x', '-y', f'-o{out}', path], check=True, stdout=subprocess.DEVNULL)
    prices = {}
    for category in GAMES.values():
        found = prices.setdefault(category, {})
        for file in glob.glob(os.path.join(out, '*', str(category), '*', 'prices')):
            try:
                with open(file, encoding='utf-8') as f:
                    results = json.load(f).get('results') or []
            except (OSError, ValueError):
                continue
            for r in results:
                price = r.get('marketPrice') or r.get('midPrice')
                if price and price > 0 and r.get('subTypeName'):
                    found.setdefault(r['productId'], {})[r['subTypeName']] = round(float(price), 2)
    shutil.rmtree(out, ignore_errors=True)
    os.remove(path)
    return prices


def load(folder):
    files = {}
    for path in glob.glob(os.path.join(folder, '*.json')):
        try:
            with open(path, encoding='utf-8') as f:
                files[os.path.basename(path)[:-5]] = json.load(f)
        except (OSError, ValueError):
            pass
    return files


def entry_for(files, game, info):
    """La serie de un producto dentro de los archivos (la crea si no está)."""
    file, key, group, name = info
    data = files.setdefault(file, {'version': 1, 'set': group if game == 'pokemon' else file, 'cards': {}})
    cards = data['cards']
    if game == 'pokemon':
        card = cards.setdefault(key, {'name': name})
    else:
        card = cards.setdefault(key, {}).setdefault(group, {'name': name})
    return card


def add_point(series, day, price):
    if not series or series[-1][1] != price:
        if series and series[-1][0] >= day:
            return
        series.append([day, price])


def trim(series, cutoff):
    old = [p for p in series if p[0] < cutoff]
    keep = [p for p in series if p[0] >= cutoff]
    return (old[-1:] if old and (not keep or keep[0][0] > cutoff) else []) + keep


def series_of(card):
    return [k for k, v in card.items() if k != 'name' and isinstance(v, list)]


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    out, tmp = sys.argv[1:]
    os.makedirs(tmp, exist_ok=True)
    latest = datetime.date.fromisoformat(get(f'{API}/last-updated.txt').decode()[:10])
    infos = {}
    for game in GAMES:
        try:
            with open(os.path.join(out, f'{game}-info.json'), encoding='utf-8') as f:
                infos[game] = json.load(f)
        except (OSError, ValueError):
            infos[game] = {}
    throughs = [infos[g].get('through') for g in GAMES]
    through = min((datetime.date.fromisoformat(t) for t in throughs if t), default=None) if all(throughs) else None
    days = schedule(through, latest)[:MAX_DAYS_PER_RUN]
    if not days:
        print(f'Pokémon y Yu-Gi-Oh!: ya está al día ({latest}).')
        return
    print(f'Pokémon y Yu-Gi-Oh!: leo {len(days)} días, del {days[0]} al {days[-1]}.')
    catalogs = {game: read_products(game, cat) for game, cat in GAMES.items()}
    folders = {game: os.path.join(out, game) for game in GAMES}
    files = {game: load(folders[game]) for game in GAMES}
    done = None
    for day in days:
        prices = read_archive(day, tmp)
        if prices is None:
            continue
        iso = day.isoformat()
        for game, cat in GAMES.items():
            products = catalogs[game][0]
            for pid, finishes in prices.get(cat, {}).items():
                info = products.get(pid)
                if not info:
                    continue
                card = entry_for(files[game], game, info)
                for finish, price in finishes.items():
                    add_point(card.setdefault(finish, []), iso, price)
        done = iso
        print(f'  {iso} listo')
    if done is None:
        raise SystemExit('No se pudo leer ningún día: queda el historial anterior.')
    cutoff = (latest - datetime.timedelta(days=MAX_DAYS)).isoformat()
    today = datetime.date.today().isoformat()
    for game in GAMES:
        os.makedirs(folders[game], exist_ok=True)
        total = 0
        for name, data in files[game].items():
            for card in (data['cards'].values() if game == 'pokemon' else
                         [c for e in data['cards'].values() for c in e.values()]):
                for k in series_of(card):
                    card[k] = trim(card[k], cutoff)
            total += len(data['cards'])
            data['updated'] = today
            with open(os.path.join(folders[game], f'{name}.json'), 'w', encoding='utf-8') as f:
                json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
        info = {'updated': today, 'through': done, 'sets': len(files[game]), 'cards': total,
                'files': sorted(files[game])}
        if game == 'pokemon':
            info['codes'] = dict(sorted(catalogs[game][1].items()))
        with open(os.path.join(out, f'{game}-info.json'), 'w', encoding='utf-8') as f:
            json.dump(info, f, separators=(',', ':'), ensure_ascii=False)
        print(f'Historial de {game}: {len(files[game])} archivos, {total} cartas, hasta el {done}.')


if __name__ == '__main__':
    main()
