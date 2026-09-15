
##### BUILD #####
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json tsconfig.json ./
RUN npm install

COPY src/ ./src/
RUN npm run build


##### RUN #####
FROM node:22-alpine AS runner

WORKDIR /app

COPY --from=builder /app/dist/ ./

EXPOSE 11434

USER node

CMD ["node", "index.js"]
