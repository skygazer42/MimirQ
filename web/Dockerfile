FROM node:20-alpine

RUN corepack enable
WORKDIR /app

# 复制依赖文件
COPY package.json pnpm-lock.yaml ./

# 安装依赖
RUN pnpm install --frozen-lockfile

# 复制应用代码
COPY . .
RUN chown -R node:node /app

# 暴露端口
EXPOSE 3000

# 启动命令
USER node
CMD ["pnpm", "dev"]
