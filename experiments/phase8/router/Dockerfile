
##### BUILD #####
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json tsconfig.json ./
RUN npm install

COPY src/ ./src/
RUN npm run build


##### RUN #####
FROM node:22-alpine AS runner

WORKDIR /app

COPY package.json package-lock.json ./
COPY --from=builder /app/dist/ ./
RUN npm install --omit=dev

EXPOSE 11434

USER node

CMD ["node", "index.js"]
