# Frontend Dockerfile
FROM node:20-alpine

WORKDIR /app

# Install dependencies (only copy package.json first for cache)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code
COPY . .

# Expose port
EXPOSE 3000

# Command to run (dev mode)
CMD ["npm", "run", "dev"]
# For production, we would use: RUN npm run build && CMD ["npm", "start"]
