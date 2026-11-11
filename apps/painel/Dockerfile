# Build do Vite e nginx servindo o SPA. O nginx também faz proxy de `/admin`
# para a API: painel e API na mesma origem, sem CORS (cookie SameSite=Strict).
FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
