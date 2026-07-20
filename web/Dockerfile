FROM node:20-alpine

RUN corepack enable
WORKDIR /app

# 复制依赖文件
COPY package.json pnpm-lock.yaml ./

# 安装依赖
RUN pnpm install --frozen-lockfile

# 复制应用代码
COPY next.config.mjs tsconfig.json tailwind.config.ts postcss.config.mjs eslint.config.js next-env.d.ts vitest.config.ts ./
COPY app ./app
COPY components ./components
COPY contexts ./contexts
COPY hooks ./hooks
COPY i18n ./i18n
COPY lib ./lib
COPY public ./public
COPY instrumentation-client.ts ./instrumentation-client.ts
COPY proxy.ts ./proxy.ts
COPY scripts ./scripts
COPY sentry.edge.config.ts ./sentry.edge.config.ts
COPY sentry.server.config.ts ./sentry.server.config.ts
COPY store ./store
COPY types ./types
COPY workers ./workers
RUN chown -R node:node /app

# 暴露端口
EXPOSE 3000

# 启动命令
USER node
CMD ["pnpm", "dev"]
