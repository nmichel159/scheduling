CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    google_id VARCHAR(255) UNIQUE,
    picture_url TEXT,
    login_count INTEGER DEFAULT 0, -- Tu budeme pripočítavať +1
    last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    text VARCHAR(255) NOT NULL
);

INSERT INTO messages (text) VALUES ('Database connected!');