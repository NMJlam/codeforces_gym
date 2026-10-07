# Dev image: source is bind-mounted by docker-compose, Vite hot-reloads.
FROM oven/bun:1.4.2
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
CMD ["bun", "run", "dev"]
