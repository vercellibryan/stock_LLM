CREATE TABLE IF NOT EXISTS company (
    symbol TEXT NOT NULL,
    name TEXT,
    sector TEXT,
    industry TEXT,
    description TEXT,
    updated_at DATE DEFAULT (datetime('now')),
    PRIMARY KEY (symbol)
);

CREATE TABLE IF NOT EXISTS stock (
    symbol TEXT NOT NULL,
    date DATE NOT NULL,
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume INTEGER,
    dividends REAL DEFAULT 0,
    stock_split REAL DEFAULT 0,
    PRIMARY KEY (symbol, date),
    FOREIGN KEY (symbol) REFERENCES company(symbol)
);

CREATE TABLE IF NOT EXISTS article (
    url TEXT NOT NULL,
    symbol TEXT NOT NULL,
    title TEXT,
    date DATE,
    source TEXT,
    summary TEXT,
    full_text TEXT,
    PRIMARY KEY (url),
    FOREIGN KEY (symbol) REFERENCES company(symbol)
);