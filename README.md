# 部署到 Koyeb（免费 24/7）

## 一键部署

[![Deploy to Koyeb](https://www.koyeb.com/static/images/deploy/button.svg)](https://app.koyeb.com/deploy?type=docker&repository=github.com/Mianbier/qqbot&branch=master&name=qqbot)

## 手动步骤

1. 打开 https://app.koyeb.com ，用 GitHub 登录
2. 点 **Create App**
3. 选 **Deploy from GitHub** → 授权并选 `Mianbier/qqbot`
4. Type 选 **Docker**，Branch 选 `master`
5. 点 **Environment variables**，添加：

```
BOT_APP_ID = 1905065502
BOT_SECRET = BazPpGiAd6a5a6dAiGpPzaCoR5jO4kR8
DS_PHONE = 15984379411
DS_PASSWORD = 12345djw
DATA_DIR = /app/data
```

6. Instance 选 **Nano (免费)**，点 **Deploy**

部署大约 5 分钟，之后机器人就 7×24 在线了。
