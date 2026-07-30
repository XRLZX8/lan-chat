#!/bin/bash
# 预缓存最新版 LAN Chat exe
TOKEN=$(cat /home/xrl/.key/github_repo.key)
CACHE="/home/xrl/portal/static/cache"

# 获取最新 release tag 和下载 URL
DATA=$(curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/XRLZX8/lan-chat/releases?per_page=20" | \
  python3 -c "
import sys,json,sort
data=json.load(sys.stdin)
data.sort(key=lambda r: r['published_at'], reverse=True)
for r in data:
    assets=r.get('assets',[])
    if assets:
        print(f\"{r['tag_name']}|{assets[0]['browser_download_url']}\")
        break
" 2>/dev/null)

TAG=$(echo "$DATA" | cut -d'|' -f1)
URL=$(echo "$DATA" | cut -d'|' -f2)

if [ -z "$TAG" ] || [ -z "$URL" ]; then
  exit 1
fi

mkdir -p "$CACHE"
F="$CACHE/LAN_Chat_${TAG}.exe"

if [ -f "$F" ]; then
  exit 0  # 已缓存
fi

echo "预缓存 $TAG ..."
curl -sLo "$F" "$URL"
ls -lh "$F" | awk '{print $5, $NF}'
