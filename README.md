# Mercator's Hoard

[Español](README.es.md)

A local dashboard for WatchHoard and BookHoard usage, Cults product listings and sales imported from Cults. It stores history only on this computer in `data/mercator.sqlite3`.

## Open

Run `python mercator.py` and open [http://127.0.0.1:5195](http://127.0.0.1:5195). Hoard Hub can also start it from `faustus-plugin.json` and open a dedicated window.

On launch and every six hours while running, Mercator reads Supabase Auth user counts and Cloudflare Worker requests and errors. **Refresh data** triggers an early read. The dashboard shows the last stored reading; a source without access is marked pending instead of presenting an older value as current.

## Credentials

Mercator reads `WatchHoard/watchhoard/.env` for WatchHoard. BookHoard's public key cannot count Auth users. To enable that count and Worker metrics, copy `.env.example` to `.env` and fill in the local values. Do not enter credentials into the UI or commit them. Cloudflare requires an Analytics read token for the relevant account; separate account and token settings are supported for WatchHoard and BookHoard.

## Cults sales and catalogue

Export a sales CSV from Cults, select it in **Sales**, and map the date, product and revenue columns. Currency and sale ID are optional. Comma, semicolon and tab separators are supported. Reimporting the same file does not count sales twice, including repeated identical rows without IDs.

Revenue is shown by currency. Different currencies are never summed, and revenue is not presented as net profit. Mercator does not fetch Cults sales directly because no verified API and sales schema are configured. It also reads, without modifying, product folders under `Desktop/Modelos/Contornos pokemon` and detects `cults3d.json` files. Set `MERCATOR_PRODUCTS_DIR` in `.env` to choose another folder.

## Verify

```sh
python -m unittest discover -s tests
```

The server binds only to `127.0.0.1`.
