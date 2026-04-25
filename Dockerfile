FROM node:20-alpine

WORKDIR /app

COPY package.json ./
COPY server.js ./
COPY index.html overview.html crops.html markets.html mydata.html ./

ENV PORT=3000
EXPOSE 3000

CMD ["node", "server.js"]
