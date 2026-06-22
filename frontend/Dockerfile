# Frontend image — Next.js 16 + React 19 (PortfolioPilot).
#
# Dev-oriented: dependencies are baked into the image, the source is
# bind-mounted by docker-compose, and `next dev` runs with file-watch polling
# (set in compose) so edits on a Windows-host bind mount trigger hot reload.
FROM node:22-slim

WORKDIR /app

# Install deps first for layer caching. package-lock.json is required by npm ci.
COPY package.json package-lock.json* ./
RUN npm ci

# Copy the source so the image works without the bind mount; in dev, compose
# bind-mounts ./frontend over this (with node_modules/.next kept as volumes).
COPY . .

EXPOSE 3000

# Bind to 0.0.0.0 so the dev server is reachable from the host.
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
