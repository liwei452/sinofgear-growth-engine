FROM node:22-alpine

WORKDIR /app
COPY frontend/package.json /app/package.json
RUN corepack enable && pnpm install --prod=false
COPY frontend /app

CMD ["pnpm", "dev"]
