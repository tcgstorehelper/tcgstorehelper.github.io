// Lista diaria de precios de Card Kingdom para la web (CLAUDE.md, secciones 5 y 8).
// Copia de scripts/ck-prices.mjs del repo privado tcg-store-helper-web: si se cambia allá, copiarlo acá también.
// La lista original pesa decenas de MB: se baja una vez por día (workflow ck-prices.yml), se achica a los campos
// que usa CardKingdomApiService en Windows y se publica como docs/app/data/ck-prices.json en MTG-Card-Store.
//
// Uso: node scripts/ck-prices.mjs <archivo de salida> [archivo de entrada ya bajado]
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export const PRICE_LIST_URL = 'https://api.cardkingdom.com/api/v2/pricelist';

/** Orden de las columnas en cada fila de "data". src/prices/cardkingdom.ts lee este mismo orden. */
export const FIELDS = ['name', 'edition', 'variation', 'sku', 'foil', 'nm', 'ex', 'vg', 'g'];
export const FORMAT_VERSION = 1;

/** "2.49" → 2.49; vacío, null o texto raro → null. */
function price(value) {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

const text = (value) => (value == null ? '' : String(value));

/**
 * Achica la lista: cada producto queda como [nombre, edición, variante, sku, foil (1/0), NM, EX, VG, G].
 * Se descartan los que no tienen nombre ni sku, porque Windows tampoco los puede emparejar.
 */
export function shrink(list, now = new Date()) {
  const products = Array.isArray(list?.data) ? list.data : [];
  const data = [];
  for (const p of products) {
    if (!p || typeof p !== 'object' || !p.name || !p.sku) continue;
    const c = p.condition_values && typeof p.condition_values === 'object' ? p.condition_values : {};
    data.push([
      text(p.name), text(p.edition), text(p.variation), text(p.sku),
      String(p.is_foil).toLowerCase() === 'true' ? 1 : 0,
      price(c.nm_price), price(c.ex_price), price(c.vg_price), price(c.g_price),
    ]);
  }
  if (!data.length) throw new Error('La lista de Card Kingdom vino vacía: no se publica para no borrar la anterior.');
  return { version: FORMAT_VERSION, updated: now.toISOString(), fields: FIELDS, data };
}

/** Lo que la web baja al abrir Inventario para mostrar de cuándo es la lista, sin bajar la lista entera. */
export const infoOf = (small) => ({ updated: small.updated, products: small.data.length });

/** ck-prices.json -> ck-prices-info.json, en la misma carpeta. */
export const infoPath = (output) => output.replace(/(\.json)?$/, '-info.json');

async function download() {
  const response = await fetch(PRICE_LIST_URL, { headers: { 'User-Agent': 'Mozilla/5.0', Accept: 'application/json' } });
  if (!response.ok) throw new Error(`Card Kingdom respondió ${response.status}`);
  return response.json();
}

async function main() {
  const [output, input] = process.argv.slice(2);
  if (!output) {
    console.error('Uso: node scripts/ck-prices.mjs <salida.json> [entrada.json]');
    process.exit(1);
  }
  const list = input ? JSON.parse(readFileSync(input, 'utf8')) : await download();
  const small = shrink(list);
  const json = JSON.stringify(small);
  writeFileSync(output, json);
  writeFileSync(infoPath(output), JSON.stringify(infoOf(small)));
  console.log(`Card Kingdom: ${small.data.length} productos, ${(json.length / 1e6).toFixed(1)} MB.`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main().catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
}
