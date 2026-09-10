# talk_talk — 景区英语跟读评分

## 已实现
1. 每个对话卡片底部：按住录音按钮跟读商家英文
2. 浏览器语音识别（Web Speech API）转文字
3. 后端调用火山方舟豆包 Seed，返回三维分数：
   - 发音准确度 pronunciation
   - 流利度 fluency
   - 完整度 completeness
4. 综合分评级：优秀（≥85）/ 不错（≥60）/ 再练一次（<60）

## 启动

```bash
cd talk_talk
pip install -r requirements.txt
python server.py
```

浏览器打开：http://127.0.0.1:5000/  
请使用 **Chrome / Edge**，并允许麦克风权限。

本地需设置环境变量后再启动（PowerShell 示例）：

```powershell
$env:ARK_API_KEY="你的方舟密钥"
$env:ARK_MODEL="doubao-seed-1-8-251228"   # 可选
python server.py
```

若模型暂时不可用或未设置 Key，后端会自动使用本地文本相似度兜底评分。

## 部署到 Render（推荐）
1. 把 `talk_talk` 做成 GitHub 公开或私有仓库并推送
2. 打开 https://dashboard.render.com → New → Web Service → 连接该仓库
3. 设置：
   - Root Directory：若仓库根就是 `talk_talk` 则留空；若在子目录则填 `talk_talk`
   - Runtime：Python
   - Build Command：`pip install -r requirements.txt`
   - Start Command：`gunicorn -b 0.0.0.0:$PORT server:app`
4. Environment → Add：
   - `ARK_API_KEY` = 你的方舟密钥
   - `ARK_MODEL` = `doubao-seed-1-8-251228`（可选）
5. Create Web Service，等待 Deploy 成功后，用 Render 给的 `https://xxx.onrender.com` 打开即可

免费档闲置后可能休眠，首次打开会稍慢。

## 安全提醒
API Key 只放在环境变量里，不要写进前端 HTML，也不要提交到 GitHub。
