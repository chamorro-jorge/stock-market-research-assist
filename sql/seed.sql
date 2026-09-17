-- Datos iniciales: un usuario y su watchlist.
-- Ejecutar DESPUÉS de schema.sql. Es idempotente.

INSERT INTO users (email, display_name)
VALUES ('ayerbedev@gmail.com', 'Jorge')
ON CONFLICT (email) DO NOTHING;

INSERT INTO watchlists (user_id, name)
SELECT id, 'Default' FROM users WHERE email = 'ayerbedev@gmail.com'
ON CONFLICT (user_id, name) DO NOTHING;

-- Cinco sectores distintos, para que la búsqueda semántica tenga que
-- discriminar de verdad y no devuelva siempre lo mismo.
INSERT INTO watchlist_tickers (watchlist_id, ticker)
SELECT w.id, t.ticker
FROM watchlists w
JOIN users u ON u.id = w.user_id
CROSS JOIN (VALUES ('AAPL'), ('MSFT'), ('NVDA'), ('JPM'), ('XOM')) AS t(ticker)
WHERE u.email = 'ayerbedev@gmail.com' AND w.name = 'Default'
ON CONFLICT (watchlist_id, ticker) DO NOTHING;

-- Comprobación
SELECT u.email, w.name AS watchlist, wt.ticker
FROM watchlist_tickers wt
JOIN watchlists w ON w.id = wt.watchlist_id
JOIN users u ON u.id = w.user_id
ORDER BY wt.ticker;
