FROM node:20-alpine

RUN corepack enable && mkdir -p /app && chown -R node:node /app
WORKDIR /app
USER node

# 复制依赖文件
COPY --chown=node:node package.json pnpm-lock.yaml ./

# 安装依赖
RUN pnpm install --frozen-lockfile

# 复制应用代码
COPY --chown=node:node app ./app
COPY --chown=node:node components ./components
COPY --chown=node:node contexts ./contexts
COPY --chown=node:node hooks ./hooks
COPY --chown=node:node lib ./lib
COPY --chown=node:node public ./public
COPY --chown=node:node services ./services
COPY --chown=node:node store ./store
COPY --chown=node:node types ./types
COPY --chown=node:node workers ./workers
COPY --chown=node:node next.config.mjs next-env.d.ts openapi.json postcss.config.mjs tailwind.config.ts tsconfig.json ./

# 暴露端口
EXPOSE 3000

# 启动命令
CMD ["pnpm", "dev"]
