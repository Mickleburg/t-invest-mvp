FROM node:22-alpine
WORKDIR /app/frontend
COPY frontend/package.json frontend/dev-server.mjs ./
COPY frontend/src ./src
ENV HOST=0.0.0.0 PORT=5173 API_UPSTREAM=http://backend:8000
USER node
EXPOSE 5173
CMD ["node","dev-server.mjs"]
