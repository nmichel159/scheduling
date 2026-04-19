CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    picture_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pôvodná tabuľka môže ostať
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    text VARCHAR(255) NOT NULL
);