FROM node:20-alpine

WORKDIR /app

# Install deps in a separate layer for build cache friendliness
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy source
COPY . .

EXPOSE 5173

# --host 0.0.0.0 makes Vite reachable from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
