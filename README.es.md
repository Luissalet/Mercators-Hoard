# Mercator's Hoard

[English](README.md)

Panel local para seguir WatchHoard y BookHoard, las fichas de productos de Cults y las ventas que importes desde Cults.

## Abrir

Desde esta carpeta, ejecuta `python mercator.py` y abre [http://127.0.0.1:5195](http://127.0.0.1:5195). También puede arrancarse desde Hoard Hub mediante `faustus-plugin.json`. El panel conserva los históricos en `data/mercator.sqlite3`, únicamente en este equipo.

Al abrir Mercator, y después cada seis horas mientras siga funcionando, se consultan usuarios de Supabase Auth y peticiones/errores de Cloudflare Workers. Pulsa **Actualizar datos** para adelantar la consulta. La pantalla inicial muestra la última lectura guardada; una fuente sin acceso se marca como pendiente y no presenta como actual una cifra anterior.

## Accesos

Mercator lee `WatchHoard/watchhoard/.env` para WatchHoard. La clave pública de BookHoard no permite contar usuarios de Auth. Para activar esa lectura y las métricas de Workers, copia `.env.example` como `.env` y completa los valores. No pongas claves en la interfaz ni en Git.

Cloudflare requiere un token con permiso de lectura de Analytics para la cuenta que aloja los Workers `watchhoard` y `bookhoard`. Si están en cuentas distintas, `.env.example` permite indicar token y cuenta para cada proyecto.

## Ventas de Cults

Exporta un CSV de ventas desde Cults, elígelo en la sección **Ventas** y asigna las columnas de fecha, producto e ingreso. Puedes indicar moneda e ID de venta. La importación acepta coma, punto y coma o tabulador, y evita volver a contar la misma fila al importar el mismo archivo otra vez. Si no hay ID, distingue ventas idénticas repetidas dentro del archivo por su posición relativa entre iguales.

Los ingresos se muestran por moneda, sin sumar monedas diferentes ni asumir que el importe es beneficio neto. Mercator no consulta Cults en directo hasta disponer de un acceso y un esquema de ventas comprobados.

## Catálogo

Lee, sin modificar, las subcarpetas de `Desktop/Modelos/Contornos pokemon` y detecta cuáles tienen `cults3d.json`. Puedes cambiar la ubicación con `MERCATOR_PRODUCTS_DIR` en `.env`.

## Verificar

`python -m unittest discover -s tests` comprueba importación, límites de acceso y comportamiento de la lectura. El servidor está limitado a `127.0.0.1`; no lo expongas a la red con claves de servidor cargadas.
