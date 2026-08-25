# 腾讯云轻量服务器部署

## 服务器准备

以 Ubuntu 22.04/24.04 为例：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm nginx redis-server git
sudo systemctl enable --now redis-server
```

## 部署项目

```bash
sudo mkdir -p /var/www/enterprise-travel-agent
sudo chown -R "$USER":"$USER" /var/www/enterprise-travel-agent
cd /var/www/enterprise-travel-agent
git clone <你的 GitHub 仓库地址> .
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
npm install
npm run build
```

在服务器创建 `server/.env`，只填写服务器端密钥和配置，不要提交到 GitHub：

```text
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_MODEL=deepseek-v4-flash
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
ENABLE_TRVL_MCP=false
```

首次部署建议先将 `ENABLE_TRVL_MCP` 设为 `false`，确认基础对话、RAG、天气和搜索可用后，再单独安装并开启 Linux 版本 trvl。

## 启动 FastAPI

```bash
sudo cp deploy/enterprise-travel-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now enterprise-travel-agent
curl http://127.0.0.1:8000/api/health
```

## 配置 Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/enterprise-travel-agent
sudo ln -s /etc/nginx/sites-available/enterprise-travel-agent /etc/nginx/sites-enabled/enterprise-travel-agent
sudo nginx -t
sudo systemctl reload nginx
```

之后通过腾讯云公网 IP 访问页面。腾讯云安全组需要放行 TCP 80；配置域名和 HTTPS 时再放行 443。

## 查看日志

```bash
sudo journalctl -u enterprise-travel-agent -f
sudo systemctl status enterprise-travel-agent
```
