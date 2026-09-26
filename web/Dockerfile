# Local-development image for docker-compose (Vite dev server).
# Production does not use this: Render builds web/ as a Static Site.
FROM node:22-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
