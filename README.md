# TCG Store Helper

Sitio público de TCG Store Helper: https://tcgstorehelper.github.io/

- `/` inicio (castellano), `/en/` inglés, privacidad y términos.
- `/app/` la web, compilada. No se edita a mano: la publica el workflow "Publicar web" del repo privado.
- Rama `datos`: lista de precios de Card Kingdom (cada 1 h 05 min) e historial de precios de mercado (`historial/`, una vez por día: Magic de MTGJSON, Pokémon y Yu-Gi-Oh! de TCGCSV). La escribe solo el workflow `.github/workflows/precios.yml`, siempre como un único commit que se pisa, así el repo no crece. La web la lee de `https://raw.githubusercontent.com/tcgstorehelper/tcgstorehelper.github.io/datos/`.
