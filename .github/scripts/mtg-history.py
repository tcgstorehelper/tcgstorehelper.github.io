#!/usr/bin/env python3
"""Historial de precios de mercado de Magic para la pantalla "Historial de precios" de la web.

Fuente: MTGJSON (gratis, https://mtgjson.com). AllPrices trae los últimos 90 días de precios de venta de Card Kingdom y
TCGplayer de cada impresión, y AllIdentifiers dice a qué edición y número corresponde cada una. Se leen de a pedazos
(son archivos de cientos de MB) y se escribe un archivo chico por edición:

  <salida>/mtg/<set>.json  {"version":1,"set":"cmm","updated":"2026-11-09","cards":{"410":{"name":"Sol Ring",
                             "ck":[["2026-08-11",2.49],["2026-09-02",2.79]],"ckf":[...],"tcg":[...],"tcgf":[...]}}}
  <salida>/mtg-info.json   {"updated":"2026-11-09","sets":812,"cards":98000}

Cada serie guarda solo los días en que el precio cambió ([fecha, precio]). Si ya había un archivo de la edición, se
conserva lo anterior a lo que trae MTGJSON, así el historial crece más allá de 90 días (hasta MAX_DAYS).

Uso: python3 mtg-history.py <AllPrices.json.xz> <AllIdentifiers.json.xz> <carpeta de salida>
"""
import datetime
import json
import lzma
import os
import sys

import ijson

MAX_DAYS = 730
# Nombre corto de cada serie en el archivo -> (tienda en MTGJSON, terminación).
SERIES = {'ck': ('cardkingdom', 'normal'), 'ckf': ('cardkingdom', 'foil'),
          'tcg': ('tcgplayer', 'normal'), 'tcgf': ('tcgplayer', 'foil')}


def number_key(number):
    """'0081' y '81' son la misma carta (Card Kingdom y Scryfall a veces difieren en los ceros de adelante)."""
    n = str(number or '').strip().lower()
    stripped = n.lstrip('0')
    return stripped if stripped else n


def set_file_name(code):
    """Nombre de archivo seguro para el código de edición (los de Windows no aceptan 'CON', 'PRN', etc.)."""
    safe = ''.join(c for c in code.lower() if c.isalnum() or c in '-_')
    return f'_{safe}' if safe in ('con', 'prn', 'aux', 'nul') else safe


def change_points(by_date):
    """{fecha: precio} -> [[fecha, precio], ...] solo donde cambia."""
    points = []
    for date in sorted(by_date):
        try:
            value = round(float(by_date[date]), 2)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if not points or points[-1][1] != value:
            points.append([date, value])
    return points


def merge(old, new, cutoff):
    """Lo viejo anterior al primer día que trae MTGJSON + lo nuevo, sin repetir precios iguales seguidos."""
    if not new:
        return [p for p in (old or []) if p[0] >= cutoff] or (old or [])[-1:]
    first = new[0][0]
    out = [p for p in (old or []) if p[0] < first and p[0] >= cutoff]
    for p in new:
        if not out or out[-1][1] != p[1]:
            out.append(p)
    return out


def open_json(path):
    return lzma.open(path, 'rb') if path.endswith('.xz') else open(path, 'rb')


def read_identifiers(path):
    """uuid -> (set, número, nombre)."""
    ids = {}
    with open_json(path) as f:
        for uuid, card in ijson.kvitems(f, 'data', use_float=True):
            code, number = card.get('setCode'), card.get('number')
            if code and number:
                ids[uuid] = (code.lower(), number_key(number), card.get('name') or '')
    return ids


def read_prices(path, ids):
    """set -> número -> {nombre, series}."""
    sets = {}
    with open_json(path) as f:
        for uuid, formats in ijson.kvitems(f, 'data', use_float=True):
            where = ids.get(uuid)
            paper = (formats or {}).get('paper') or {}
            if not where or not paper:
                continue
            series = {}
            for short, (store, finish) in SERIES.items():
                retail = ((paper.get(store) or {}).get('retail') or {}).get(finish) or {}
                points = change_points(retail)
                if points:
                    series[short] = points
            if not series:
                continue
            code, number, name = where
            card = sets.setdefault(code, {}).get(number)
            # Dos impresiones con el mismo número (raro): queda la que tenga más series.
            if card is None or len(series) > len(card) - 1:
                sets[code][number] = {'name': name, **series}
    return sets


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    prices_path, ids_path, out = sys.argv[1:]
    ids = read_identifiers(ids_path)
    print(f'MTGJSON: {len(ids)} impresiones con edición y número.')
    sets = read_prices(prices_path, ids)
    if not sets:
        raise SystemExit('MTGJSON no trajo precios: no se publica para no borrar el historial anterior.')
    today = datetime.date.today().isoformat()
    cutoff = (datetime.date.today() - datetime.timedelta(days=MAX_DAYS)).isoformat()
    folder = os.path.join(out, 'mtg')
    os.makedirs(folder, exist_ok=True)
    total = 0
    for code, cards in sets.items():
        path = os.path.join(folder, f'{set_file_name(code)}.json')
        old = {}
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    old = json.load(f).get('cards') or {}
            except (OSError, ValueError):
                old = {}
        merged = {}
        for number in set(old) | set(cards):
            new_card, old_card = cards.get(number) or {}, old.get(number) or {}
            card = {'name': new_card.get('name') or old_card.get('name') or ''}
            for short in SERIES:
                points = merge(old_card.get(short), new_card.get(short), cutoff)
                if points:
                    card[short] = points
            if len(card) > 1:
                merged[number] = card
        total += len(merged)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'set': code, 'updated': today, 'cards': merged}, f, separators=(',', ':'),
                      ensure_ascii=False)
    with open(os.path.join(out, 'mtg-info.json'), 'w', encoding='utf-8') as f:
        json.dump({'updated': today, 'sets': len(sets), 'cards': total}, f)
    print(f'Historial de Magic: {len(sets)} ediciones, {total} cartas.')


if __name__ == '__main__':
    main()
