FROM node:20-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
# `npm install` rather than `npm ci` because optional platform deps (e.g.
# @emnapi/*) make strict lock-file sync brittle across Linux variants.
RUN npm install --no-audit --no-fund

COPY . .

# Build with the default API base; runtime NUXT_PUBLIC_API_BASE wins
# because Nuxt re-reads NUXT_PUBLIC_* env vars on server start.
RUN npm run build


FROM node:20-bookworm-slim AS runtime

WORKDIR /app
COPY --from=build /app/.output ./.output

ENV HOST=0.0.0.0
ENV PORT=3000

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
