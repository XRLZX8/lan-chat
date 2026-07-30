#!/bin/bash
# 从 GitHub Releases 下载最新版 LAN Chat .exe 到 portal 静态目录
TOKEN=$(cat /home/xrl/.key/github_repo.key)
REPO="XRLZX8/lan-chat"
DEST="/home/xrl/portal/static/LAN_Chat.exe"

# 获取最新 release 的下载 URL
URL=$(curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/$REPO/releases/latest" | \
  python3 -c "import sys,json; r=json.load(sys.stdin); \
  [print(a['browser_download_url']) for a in r.get('assets',[]) if a['name'].endswith('.exe')]" 2>/dev/null | head -1)

if [ -z "$URL" ]; then
  echo "未找到最新 release 的 exe 文件"
  exit 1
fi

echo "下载: $URL"
curl -sL -o "$DEST" "$URL"
ls -lh "$DEST"
echo "✅ 已更新: $DEST"
